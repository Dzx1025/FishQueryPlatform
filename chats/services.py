"""
RAG (Retrieval Augmented Generation) Service Module.

This module provides AI-powered question answering with citation support:
1. Vector search via Qdrant for semantic document retrieval
2. Cross-encoder reranking for improved relevance
3. LLM response generation with inline citations [citation:N]

All I/O operations are async to avoid blocking the event loop.
CPU-bound operations (reranking) run in a thread pool.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Any, TypedDict

import httpx
from django.conf import settings
from loguru import logger
from qdrant_client import AsyncQdrantClient
from sentence_transformers import CrossEncoder
from openai import AsyncOpenAI
from openai.types.responses import EasyInputMessageParam


class StreamEventType(Enum):
    """
    Stream event types for RAG responses.

    Used by views.py to format SSE or AI SDK protocol responses.
    """

    SOURCES = "sources"  # Retrieved source documents for citation lookup
    TEXT_DELTA = "text"  # Incremental LLM text chunk
    DONE = "done"  # Stream completed successfully
    ERROR = "error"  # Error occurred during processing


@dataclass
class SourceDocument:
    """
    Represents a retrieved source document.

    Attributes:
        index: 1-based index for citation reference (e.g., [citation:1])
        content: Full document content
        metadata: Document metadata (url, title, etc.)
        score: Relevance score (rerank_score if reranked, else vector similarity)
    """

    index: int
    content: str
    metadata: dict
    score: float


@dataclass
class StreamEvent:
    """
    Structured stream event for RAG responses.

    Decouples business logic from transport format.
    Views layer converts these to SSE or AI SDK protocol.
    """

    type: StreamEventType
    data: dict | str | list | None = None


class SourceDict(TypedDict):
    """Type definition for source data sent to frontend."""

    index: int
    content: str
    metadata: dict
    score: float


# Thread pool for CPU-bound operations (reranking model inference)
# Limited to 2 workers to avoid memory issues with model loading
_rerank_executor = ThreadPoolExecutor(max_workers=2)


class AIService:
    """
    Service class for AI-powered RAG (Retrieval Augmented Generation).

    Responsibilities:
    - Generate query embeddings via Nomic API
    - Search Qdrant vector database for relevant documents
    - Rerank results using cross-encoder model
    - Generate streaming LLM responses with citations

    All clients are lazy-loaded on first use.

    Usage:
        service = AIService()
        async for event in service.process_query_stream("What is the bag limit?"):
            # Handle StreamEvent
    """

    def __init__(self):
        """
        Initialize AIService with configuration from Django settings.
        """
        # Qdrant configuration
        self.qdrant_url = settings.QDRANT_URL
        self.collection_name = settings.QDRANT_COLLECTION_NAME
        self.qdrant_api_key = settings.QDRANT_API_KEY

        # Embedding configuration
        self.nomic_token = settings.NOMIC_TOKEN
        self.nomic_url = settings.NOMIC_API_URL
        self.nomic_model = settings.NOMIC_EMBEDDING_MODEL
        self.task_type = settings.NOMIC_TASK_TYPE
        self.vector_size = settings.NOMIC_EMBEDDING_DIMENSION

        # Reranking configuration
        self.rerank_model_name = settings.RERANK_MODEL
        self.top_k = settings.RAG_TOP_K
        self.rerank_top_k = settings.RAG_RERANK_TOP_K

        # LLM configuration
        self.openai_api_key = settings.OPENAI_API_KEY
        self.openai_api_url = settings.OPENAI_API_URL
        self.openai_model = settings.OPENAI_MODEL

        self._validate_config()

        # Lazy-loaded clients
        self._qdrant_client = None
        self._rerank_model = None
        self._openai_client = None
        self._http_client = None

    def _validate_config(self):
        """Validate that required configuration parameters are present."""
        if not self.qdrant_url:
            logger.warning("Qdrant URL not provided. Vector search may not work.")
        if not self.collection_name:
            logger.warning(
                "Qdrant collection name not provided. Vector search may not work."
            )
        if not self.qdrant_api_key:
            logger.warning("Qdrant API key not provided. Vector search may not work.")
        if not self.nomic_token:
            logger.warning(
                "Nomic token not provided. Embedding generation may not work."
            )
        if not self.nomic_model:
            logger.warning(
                "Nomic embedding model not provided. Embedding generation may not work."
            )
        if not self.rerank_model_name:
            logger.warning("Rerank model name not provided. Reranking may not work.")
        if not self.openai_api_key:
            logger.warning(
                "OpenAI API key not provided. LLM functionality may not work."
            )

    @property
    def qdrant_client(self) -> AsyncQdrantClient:
        """Lazy-loaded Qdrant client."""
        if self._qdrant_client is None:
            logger.info(f"Connecting to Qdrant at: {self.qdrant_url}")
            self._qdrant_client = AsyncQdrantClient(
                url=self.qdrant_url, https=True, api_key=self.qdrant_api_key
            )
        return self._qdrant_client

    @property
    def rerank_model(self) -> CrossEncoder:
        """Lazy-loaded reranking model."""
        if self._rerank_model is None:
            logger.info(f"Loading reranking model: {self.rerank_model_name}")
            self._rerank_model = CrossEncoder(self.rerank_model_name, max_length=512)
        return self._rerank_model

    @property
    def openai_client(self) -> AsyncOpenAI:
        """Lazy-loaded OpenAI client."""
        if self._openai_client is None:
            self._openai_client = AsyncOpenAI(
                api_key=self.openai_api_key,
                base_url=self.openai_api_url if self.openai_api_url else None,
            )
        return self._openai_client

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy-loaded async HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def get_query_embedding(self, query: str) -> list[float]:
        """
        Generate embedding vector for the query text.

        Uses Nomic API for embedding generation. Async to avoid blocking
        the event loop during HTTP request.

        Args:
            query: User's question text

        Returns:
            768-dimensional embedding vector

        Raises:
            Exception: If embedding generation fails after retries
        """
        logger.info(f"Generating embedding for query: {query}")

        headers = {
            "Authorization": f"Bearer {self.nomic_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.nomic_model,
            "texts": [query],
            "task_type": self.task_type,
            "dimensionality": self.vector_size,
        }

        max_retries = 3

        for attempt in range(max_retries):
            try:
                response = await self.http_client.post(
                    self.nomic_url,
                    headers=headers,
                    json=payload,
                )

                if response.status_code == 200:
                    embedding = response.json()["embeddings"][0]
                    logger.success("Generated embedding for query successfully")
                    return embedding
                elif response.status_code == 429:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(
                        f"Rate limited by Nomic API. Retrying in {wait_time} seconds..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"Nomic API error: {response.status_code} - {response.text}"
                    )
                    raise Exception(f"Failed to get embedding: {response.text}")

            except httpx.RequestError as e:
                if attempt >= max_retries - 1:
                    logger.error(
                        f"Failed to get embedding after {max_retries} retries: {e}"
                    )
                    raise
                wait_time = 2 ** (attempt + 1)
                logger.warning(
                    f"Error connecting to Nomic API. Retrying in {wait_time} seconds... Error: {e}"
                )
                await asyncio.sleep(wait_time)

        raise Exception("Failed to generate embedding for query")

    async def search_qdrant(
        self, query_embedding: list[float], top_k: int | None = None
    ) -> list[dict]:
        """
        Search Qdrant vector database for similar documents.

        Args:
            query_embedding: Query vector from get_query_embedding()
            top_k: Number of results to retrieve (default: self.top_k)

        Returns:
            List of documents with page_content, metadata, and score
        """
        if top_k is None:
            top_k = self.top_k

        logger.info(f"Searching Qdrant for top {top_k} results")

        try:
            search_results = await self.qdrant_client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                limit=top_k,
                score_threshold=0.5,
            )

            documents = []
            for point in search_results.points:
                documents.append(
                    {
                        "page_content": point.payload["page_content"],
                        "metadata": point.payload["metadata"],
                        "score": point.score,
                    }
                )

            logger.success(f"Found {len(documents)} results from Qdrant")
            return documents
        except Exception as e:
            logger.error(f"Failed to search Qdrant: {e}")
            raise

    def _rerank_sync(self, query: str, documents: list[dict], top_k: int) -> list[dict]:
        """
        Synchronous reranking using cross-encoder model.

        This is CPU-bound (model inference), called via run_in_executor
        in rerank_results() to avoid blocking the event loop.
        """
        pairs = [(query, doc["page_content"]) for doc in documents]
        scores = self.rerank_model.predict(pairs)

        for i, score in enumerate(scores):
            documents[i]["rerank_score"] = float(score)

        reranked_documents = sorted(
            documents, key=lambda x: x["rerank_score"], reverse=True
        )
        return reranked_documents[:top_k]

    async def rerank_results(
        self, query: str, documents: list[dict], top_k: int | None = None
    ) -> list[dict]:
        """
        Rerank documents using cross-encoder model (async wrapper).

        Runs CPU-bound inference in thread pool to avoid blocking.
        Falls back to original vector similarity scores on error.

        Args:
            query: User's question
            documents: Documents from vector search
            top_k: Number of top results to return

        Returns:
            Reranked documents with rerank_score field added
        """
        if top_k is None:
            top_k = self.rerank_top_k

        logger.info(f"Reranking {len(documents)} documents")

        try:
            loop = asyncio.get_event_loop()
            top_results = await loop.run_in_executor(
                _rerank_executor,
                self._rerank_sync,
                query,
                documents,
                top_k,
            )
            logger.success(
                f"Reranked documents and selected top {len(top_results)} results"
            )
            return top_results
        except Exception as e:
            logger.error(f"Failed to rerank results: {e}")
            logger.warning("Falling back to original scores")
            return sorted(documents, key=lambda x: x["score"], reverse=True)[:top_k]

    def _build_sources(self, documents: list[dict]) -> list[SourceDocument]:
        """
        Convert raw documents to SourceDocument objects.

        Assigns 1-based indices for citation references (e.g., [citation:1]).
        """
        return [
            SourceDocument(
                index=i + 1,
                content=doc["page_content"],
                metadata=doc["metadata"],
                score=doc.get("rerank_score", doc.get("score", 0.0)),
            )
            for i, doc in enumerate(documents)
        ]

    def _get_response_instruction(self) -> str:
        """
        Get the system instruction for LLM response generation.

        Instructs the LLM to:
        - Use [citation:N] format for inline citations
        - Cite every factual claim
        - Be concise and professional
        """
        return (
            "You are an expert in Australian recreational fishing regulations, particularly those published by "
            "the Department of Primary Industries and Regional Development, Government of Western Australia. "
            "You will be given a set of related contexts to the question, which are numbered sequentially starting from 1. "
            "\n\n"
            "CITATION FORMAT: You MUST cite sources using the exact format [citation:N] where N is the context number. "
            "Place citations immediately after the relevant statement. Examples:\n"
            "- Single citation: 'The bag limit is 2 fish per day [citation:1].'\n"
            "- Multiple citations: 'Barramundi must be at least 55cm [citation:1][citation:3].'\n"
            "\n"
            "RULES:\n"
            "1. Every factual claim must have at least one citation.\n"
            "2. Place [citation:N] at the end of the sentence or clause it supports.\n"
            "3. Use multiple citations when information comes from multiple sources.\n"
            "4. Do not fabricate citations - only cite contexts that actually support your statement.\n"
            "5. Do not repeat the contexts verbatim.\n"
            "\n"
            "Your answer must be correct, accurate and written by an expert using an unbiased and professional tone. "
            "Please limit to 1024 tokens. Do not give any information that is not related to the question. "
            "Say 'information is missing on' followed by the related topic, if the given context do not provide sufficient information. "
            "Be concise."
        )

    async def generate_response_stream(
        self, query: str, sources: list[SourceDocument]
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Generate streaming response yielding structured StreamEvent objects.

        Stream order:
        1. SOURCES event - Contains all source documents for citation lookup
        2. TEXT_DELTA events - LLM response chunks with inline [citation:N] markers
        3. DONE event - Stream complete
        """
        formatted_context = "\n\n".join(
            f"[Context {src.index}]: {src.content}" for src in sources
        )

        messages: list[EasyInputMessageParam] = [
            {"role": "developer", "content": f"Context:\n{formatted_context}"},
            {"role": "user", "content": query},
        ]

        try:
            sources_data: list[SourceDict] = [
                {
                    "index": src.index,
                    "content": (
                        src.content[:200] + "..."
                        if len(src.content) > 200
                        else src.content
                    ),
                    "metadata": src.metadata,
                    "score": src.score,
                }
                for src in sources
            ]
            yield StreamEvent(type=StreamEventType.SOURCES, data=sources_data)

            kwargs: dict[str, Any] = dict(
                model=self.openai_model,
                input=messages,
                instructions=self._get_response_instruction(),
                max_output_tokens=4096,
                stream=True,
            )

            if self.openai_model not in {
                "gpt-5",
                "gpt-5.1",
                "gpt-5.2",
                "gpt-5-chat-latest",
                "gpt-5.1-chat-latest",
                "gpt-5.2-chat-latest",
                "gpt-5-mini",
                "gpt-5-nano",
                "gpt-5.1-codex",
                "gpt-5.1-codex-max",
                "gpt-5-codex",
                "gpt-5-pro",
                "gpt-5.2-pro",
            }:
                kwargs["temperature"] = 0.1

            stream = await self.openai_client.responses.create(**kwargs)

            async for event in stream:
                if event.type == "response.output_text.delta":
                    yield StreamEvent(type=StreamEventType.TEXT_DELTA, data=event.delta)

            yield StreamEvent(type=StreamEventType.DONE, data={"finishReason": "stop"})

        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            yield StreamEvent(type=StreamEventType.ERROR, data=str(e))

    async def process_query_stream(
        self, query: str, use_reranking: bool = True
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Main entry point for streaming RAG responses.

        Pipeline:
        1. Generate query embedding
        2. Search Qdrant for relevant documents
        3. Rerank results (optional)
        4. Stream LLM response with citations

        Args:
            query: User's question
            use_reranking: Whether to apply cross-encoder reranking

        Yields:
            StreamEvent objects (SOURCES, TEXT_DELTA, DONE, or ERROR)
        """
        try:
            query_embedding = await self.get_query_embedding(query)
            search_results = await self.search_qdrant(query_embedding)

            if use_reranking and search_results:
                final_results = await self.rerank_results(query, search_results)
            else:
                final_results = sorted(
                    search_results, key=lambda x: x["score"], reverse=True
                )[: self.rerank_top_k]

            if not final_results:
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    data="I don't have any knowledge base to help answer your question.",
                )
                yield StreamEvent(
                    type=StreamEventType.DONE, data={"finishReason": "stop"}
                )
                return

            sources = self._build_sources(final_results)

            async for event in self.generate_response_stream(query, sources):
                yield event

        except Exception as e:
            logger.error(f"Query processing failed: {e}")
            yield StreamEvent(type=StreamEventType.ERROR, data=str(e))

    async def process_query(self, query: str, use_reranking: bool = True) -> str:
        """
        Process a query and return the complete response as a string.

        Non-streaming alternative to process_query_stream().
        Useful for testing or non-interactive use cases.
        """
        full_response = ""

        async for event in self.process_query_stream(query, use_reranking):
            if event.type == StreamEventType.TEXT_DELTA:
                full_response += event.data
            elif event.type == StreamEventType.ERROR:
                return f"Error: {event.data}"

        return full_response

    async def close(self):
        """
        Close async resources (HTTP client).

        Call this when shutting down to properly release connections.
        """
        if self._http_client:
            await self._http_client.aclose()


# --- Singleton Instance ---
_ai_service_instance: AIService | None = None


def get_ai_service() -> AIService:
    """
    Get the singleton AIService instance.

    Avoids repeated initialization of lazy-loaded clients (Qdrant, OpenAI, etc.)
    across requests.

    Usage:
        from chats.services import get_ai_service

        ai_service = get_ai_service()
        async for event in ai_service.process_query_stream(query):
            ...
    """
    global _ai_service_instance
    if _ai_service_instance is None:
        _ai_service_instance = AIService()
    return _ai_service_instance
