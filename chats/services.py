import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Any

import requests
from loguru import logger
from qdrant_client import AsyncQdrantClient
from sentence_transformers import CrossEncoder
from openai import AsyncOpenAI
from openai.types.responses import EasyInputMessageParam


class StreamEventType(Enum):
    """Stream event types for RAG responses."""

    SOURCES = "sources"  # Retrieved source documents
    TEXT_DELTA = "text"  # LLM text chunk
    DONE = "done"  # Stream complete
    ERROR = "error"  # Error occurred


@dataclass
class SourceDocument:
    """Represents a retrieved source document."""

    index: int  # 1-based index for citation reference
    content: str  # Document content
    metadata: dict  # Document metadata (url, title, etc.)
    score: float  # Relevance score


@dataclass
class StreamEvent:
    """Structured stream event data."""

    type: StreamEventType
    data: dict | str | list | None = None


class AIService:
    """
    Service class for handling AI-powered RAG (Retrieval Augmented Generation) capabilities.
    This service encapsulates vector search, reranking, and LLM functionalities.
    """

    def __init__(self):
        """Initialize the AIService with configuration."""
        # Qdrant configuration
        self.qdrant_url = os.environ.get("QDRANT_URL")
        self.collection_name = os.environ.get("COLLECTION_NAME")
        self.qdrant_api_key = os.environ.get("QDRANT_API_KEY")

        # Embedding configuration
        self.nomic_token = os.environ.get("NOMIC_TOKEN")
        self.nomic_url = "https://api-atlas.nomic.ai/v1/embedding/text"
        self.nomic_model = os.environ.get("EMBEDDING_MODEL")
        self.task_type = "search_query"
        self.vector_size = 768

        # Reranking configuration
        self.rerank_model_name = os.environ.get("RERANK_MODEL")
        self.top_k = int(os.environ.get("TOP_K", 10))
        self.rerank_top_k = int(os.environ.get("RERANK_TOP_K", 5))

        # LLM configuration
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        self.openai_api_url = os.environ.get("OPENAI_API_URL")
        self.openai_model = os.environ.get("OPENAI_MODEL")

        self._validate_config()

        # Lazy-loaded clients
        self._qdrant_client = None
        self._rerank_model = None
        self._openai_client = None

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

    def get_query_embedding(self, query: str) -> list[float]:
        """Generate embedding for the query text."""
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
        retry_count = 0

        while retry_count < max_retries:
            try:
                response = requests.post(self.nomic_url, headers=headers, json=payload)

                if response.status_code == 200:
                    embedding = response.json()["embeddings"][0]
                    logger.success("Generated embedding for query successfully")
                    return embedding
                elif response.status_code == 429:
                    retry_count += 1
                    wait_time = 2**retry_count
                    logger.warning(
                        f"Rate limited by Nomic API. Retrying in {wait_time} seconds..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Nomic API error: {response.status_code} - {response.text}"
                    )
                    raise Exception(f"Failed to get embedding: {response.text}")
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(
                        f"Failed to get embedding after {max_retries} retries: {e}"
                    )
                    raise
                wait_time = 2**retry_count
                logger.warning(
                    f"Error connecting to Nomic API. Retrying in {wait_time} seconds... Error: {e}"
                )
                time.sleep(wait_time)

        raise Exception("Failed to generate embedding for query")

    async def search_qdrant(
        self, query_embedding: list[float], top_k: int | None = None
    ) -> list[dict]:
        """Search Qdrant using the query embedding."""
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

    def rerank_results(
        self, query: str, documents: list[dict], top_k: int | None = None
    ) -> list[dict]:
        """Rerank the results using a cross-encoder model."""
        if top_k is None:
            top_k = self.rerank_top_k

        logger.info(f"Reranking {len(documents)} documents")

        try:
            pairs = [(query, doc["page_content"]) for doc in documents]
            scores = self.rerank_model.predict(pairs)

            for i, score in enumerate(scores):
                documents[i]["rerank_score"] = float(score)

            reranked_documents = sorted(
                documents, key=lambda x: x["rerank_score"], reverse=True
            )
            top_results = reranked_documents[:top_k]
            logger.success(
                f"Reranked documents and selected top {len(top_results)} results"
            )
            return top_results
        except Exception as e:
            logger.error(f"Failed to rerank results: {e}")
            logger.warning("Falling back to original scores")
            return sorted(documents, key=lambda x: x["score"], reverse=True)[:top_k]

    def _build_sources(self, documents: list[dict]) -> list[SourceDocument]:
        """Convert raw documents to SourceDocument objects with 1-based indices."""
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
        Instructs LLM to use [citation:N] format for inline citations.
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
        # Build context from sources
        formatted_context = "\n\n".join(
            f"[Context {src.index}]: {src.content}" for src in sources
        )

        messages: list[EasyInputMessageParam] = [
            {"role": "developer", "content": f"Context:\n{formatted_context}"},
            {"role": "user", "content": query},
        ]

        try:
            # 1. Yield sources first so frontend can build citation lookup
            sources_data = [
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

            # 2. Prepare LLM request
            kwargs: dict[str, Any] = dict(
                model=self.openai_model,
                input=messages,
                instructions=self._get_response_instruction(),
                max_output_tokens=1024,
                stream=True,
            )

            NO_TEMPERATURE_MODELS = {
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
            }

            if self.openai_model not in NO_TEMPERATURE_MODELS:
                kwargs["temperature"] = 0.1

            stream = await self.openai_client.responses.create(**kwargs)

            # 3. Stream text chunks with inline citations
            async for event in stream:
                if event.type == "response.output_text.delta":
                    yield StreamEvent(type=StreamEventType.TEXT_DELTA, data=event.delta)

            # 4. Done
            yield StreamEvent(type=StreamEventType.DONE, data={"finishReason": "stop"})

        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            yield StreamEvent(type=StreamEventType.ERROR, data=str(e))

    async def process_query_stream(
        self, query: str, use_reranking: bool = True
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Process a query and yield structured StreamEvent objects.

        This is the main entry point for streaming RAG responses.
        The stream includes sources first, then text with inline citations.
        """
        try:
            query_embedding = self.get_query_embedding(query)
            search_results = await self.search_qdrant(query_embedding)

            if use_reranking and search_results:
                final_results = self.rerank_results(query, search_results)
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

            # Convert to SourceDocument objects
            sources = self._build_sources(final_results)

            async for event in self.generate_response_stream(query, sources):
                yield event

        except Exception as e:
            logger.error(f"Query processing failed: {e}")
            yield StreamEvent(type=StreamEventType.ERROR, data=str(e))

    async def process_query(self, query: str, use_reranking: bool = True) -> str:
        """
        Process a query and return the complete response as a string.
        Suitable for non-streaming use cases.
        """
        full_response = ""

        async for event in self.process_query_stream(query, use_reranking):
            if event.type == StreamEventType.TEXT_DELTA:
                full_response += event.data
            elif event.type == StreamEventType.ERROR:
                return f"Error: {event.data}"

        return full_response
