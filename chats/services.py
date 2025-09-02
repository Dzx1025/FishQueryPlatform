import json
import os
import time
from typing import Dict, List, AsyncGenerator, Optional
import requests
from loguru import logger
from qdrant_client import QdrantClient
from sentence_transformers import CrossEncoder
from openai import AsyncOpenAI


class AIService:
    """
    Service class for handling AI-powered RAG (Retrieval Augmented Generation) capabilities.
    This service encapsulates vector search, reranking, and LLM functionalities.
    """

    def __init__(self):
        """
        Initialize the AIService with configuration.
        """

        # Qdrant configuration
        self.qdrant_url = os.environ.get("QDRANT_URL")
        self.collection_name = os.environ.get("COLLECTION_NAME")
        self.qdrant_api_key = os.environ.get("QDRANT_API_KEY")

        # Nomic API configuration
        self.nomic_token = os.environ.get("NOMIC_TOKEN")
        self.nomic_url = "https://api-atlas.nomic.ai/v1/embedding/text"
        self.nomic_model = os.environ.get("EMBEDDING_MODEL")
        self.task_type = (
            "search_query"  # Using search_query for queries rather than search_document
        )
        self.vector_size = 768  # Nomic embeddings dimensionality

        # Reranking configuration
        self.rerank_model_name = os.environ.get("RERANK_MODEL")
        self.top_k = int(os.environ.get("TOP_K"))
        self.rerank_top_k = int(os.environ.get("RERANK_TOP_K"))

        # OpenAI configuration
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        self.openai_api_url = os.environ.get("OPENAI_API_URL")
        self.openai_model = os.environ.get("OPENAI_MODEL")

        # Validate required configuration
        self._validate_config()

        # Initialize client properties that will be created on demand
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
        if not self.top_k:
            logger.warning("Top K not provided. Defaulting to 10.")
            self.top_k = 10
        if not self.rerank_top_k:
            logger.warning("Rerank Top K not provided. Defaulting to 5.")
            self.rerank_top_k = 5

        if not self.openai_api_key:
            logger.warning(
                "OpenAI API key not provided. LLM functionality may not work."
            )

    @property
    def qdrant_client(self) -> QdrantClient:
        """Lazy-loaded Qdrant client."""
        if self._qdrant_client is None:
            logger.info(f"Connecting to Qdrant at: {self.qdrant_url}")
            self._qdrant_client = QdrantClient(
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
                base_url=(
                    self.openai_api_url
                    if hasattr(self, "openai_api_url") and self.openai_api_url
                    else None
                ),
            )

        return self._openai_client

    def get_query_embedding(self, query: str) -> List[float]:
        """
        Generate embedding for the query text.

        Args:
            query: The query text to embed

        Returns:
            List of embedding values
        """
        logger.info(f"Generating embedding for query: {query}")

        headers = {
            "Authorization": f"Bearer {self.nomic_token}",
            "Content-Type": "application/json",
        }

        # Prepare payload for Nomic API
        payload = {
            "model": self.nomic_model,
            "texts": [query],
            "task_type": self.task_type,
            "dimensionality": self.vector_size,
        }

        # Make API request with retry logic
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                response = requests.post(self.nomic_url, headers=headers, json=payload)

                if response.status_code == 200:
                    embedding = response.json()["embeddings"][0]
                    logger.success(f"Generated embedding for query successfully")
                    return embedding
                elif response.status_code == 429:  # Rate limit
                    retry_count += 1
                    wait_time = 2**retry_count  # Exponential backoff
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

    def search_qdrant(
        self, query_embedding: List[float], top_k: Optional[int] = None
    ) -> List[Dict]:
        """
        Search Qdrant using the query embedding.

        Args:
            query_embedding: Vector embedding to search with
            top_k: Number of results to return (defaults to self.top_k)

        Returns:
            List of document dictionaries with content, metadata and score
        """
        if top_k is None:
            top_k = self.top_k

        logger.info(f"Searching Qdrant for top {top_k} results")

        try:
            search_results = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=top_k,
            )

            # Extract documents from search results
            documents = []
            for result in search_results:
                documents.append(
                    {
                        "page_content": result.payload["page_content"],
                        "metadata": result.payload["metadata"],
                        "score": result.score,
                    }
                )

            logger.success(f"Found {len(documents)} results from Qdrant")
            return documents
        except Exception as e:
            logger.error(f"Failed to search Qdrant: {e}")
            raise

    def rerank_results(
        self, query: str, documents: List[Dict], top_k: Optional[int] = None
    ) -> List[Dict]:
        """
        Rerank the results using a cross-encoder model.

        Args:
            query: Original query text
            documents: List of documents to rerank
            top_k: Number of results to return after reranking (defaults to self.rerank_top_k)

        Returns:
            Reranked list of documents
        """
        if top_k is None:
            top_k = self.rerank_top_k

        logger.info(f"Reranking {len(documents)} documents")

        try:
            # Prepare pairs of (query, document text) for reranking
            pairs = [(query, doc["page_content"]) for doc in documents]

            # Get reranking scores
            scores = self.rerank_model.predict(pairs)

            # Add new scores to documents
            for i, score in enumerate(scores):
                documents[i]["rerank_score"] = float(score)

            # Sort by reranking score (descending)
            reranked_documents = sorted(
                documents, key=lambda x: x["rerank_score"], reverse=True
            )

            # Return top_k results
            top_results = reranked_documents[:top_k]
            logger.success(
                f"Reranked documents and selected top {len(top_results)} results"
            )
            return top_results
        except Exception as e:
            logger.error(f"Failed to rerank results: {e}")
            # Fallback to original scores if reranking fails
            logger.warning("Falling back to original scores")
            return sorted(documents, key=lambda x: x["score"], reverse=True)[:top_k]

    async def generate_response(
        self, query: str, documents: List[Dict]
    ) -> AsyncGenerator[str, None]:
        """
        Generate a streaming response using OpenAI's official client library.

        Args:
            query: User query
            documents: Retrieved documents for context

        Yields:
            Chunks of the response in the format required by the frontend
        """
        # Format documents
        formatted_context = "".join(
            f"\n\n{i}. {doc['page_content']}\n\n" for i, doc in enumerate(documents, 1)
        )

        # Create QA developer prompt
        qa_dev_prompt = (
            "You are an expert in Australian recreational fishing regulations, particularly those published by the Department of Primary Industries and Regional Development, Government of Western Australia. "
            "You will be given a set of related contexts to the question, which are numbered sequentially starting from 1. "
            "Each context has an implicit reference number based on its position in the array (first context is 1, second is 2, etc.). "
            "Please use these contexts and cite them using the format [citation:x] at the end of each sentence where applicable. "
            "Your answer must be correct, accurate and written by an expert using an unbiased and professional tone. "
            "Please limit to 1024 tokens. Do not give any information that is not related to the question, and do not repeat. "
            "Say 'information is missing on' followed by the related topic, if the given context do not provide sufficient information. "
            "If a sentence draws from multiple contexts, please list all applicable citations, like [citation:1][citation:2]. "
            "Other than code and specific names and citations, your answer must be written in the same language as the question. "
            "Be concise.\n\nContext: " + formatted_context + "\n\n"
            "Remember: Cite contexts by their position number (1 for first context, 2 for second, etc.) and don't blindly "
            "Repeat the contexts verbatim."
        )

        # Format messages for OpenAI API
        messages = [
            {"role": "developer", "content": qa_dev_prompt},
            {"role": "user", "content": query},
        ]

        try:
            # First, serialize context information for response
            serializable_context = []
            for i, doc in enumerate(documents):
                serializable_doc = {
                    "page_content": doc["page_content"].replace('"', '\\"'),
                    "metadata": doc["metadata"],
                }
                serializable_context.append(serializable_doc)

            # Escape quotes and serialize
            escaped_context = json.dumps({"context": serializable_context})

            # Define separator
            separator = "__LLM_RESPONSE__"

            # Yield context info
            yield f'0:"{escaped_context}{separator}"\n'

            # Set up streaming request to OpenAI using the official client
            stream = await self.openai_client.responses.create(
                model=self.openai_model,
                input=messages,
                max_output_tokens=1024,
                temperature=0.1,
                stream=True,
            )

            # Process streaming response
            async for event in stream:
                if event.type == "response.output_text.delta":
                    content = event.delta
                    yield f'0:"{content}"\n'

            # Return completion info
            yield 'd:{"finishReason":"stop"}\n'

        except Exception as e:
            error_message = f"Error generating LLM question: {str(e)}"
            logger.error(error_message)
            yield f"3:{error_message}\n"

    async def process_query_stream(
        self, query: str, use_reranking: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Process a query and return a streamed LLM response.
        This is suitable for Django views that support streaming responses.

        Args:
            query: User's query
            use_reranking: Whether to use the reranking step

        Yields:
            Response chunks formatted for streaming to the frontend
        """
        try:
            # Generate embedding for query
            query_embedding = self.get_query_embedding(query)

            # Search for similar documents
            search_results = self.search_qdrant(query_embedding)

            # Rerank results if enabled
            if use_reranking and search_results:
                final_results = self.rerank_results(query, search_results)
            else:
                final_results = sorted(
                    search_results, key=lambda x: x["score"], reverse=True
                )[: self.rerank_top_k]

            # Return error if no results found
            if not final_results:
                error_msg = (
                    "I don't have any knowledge base to help answer your question."
                )
                yield f'0:"{error_msg}"\n'
                yield 'd:{"finishReason":"stop","usage":{"promptTokens":0,"completionTokens":0}}\n'
                return

            # Generate LLM response with the documents
            async for chunk in self.generate_response(query, final_results):
                yield chunk

        except Exception as e:
            logger.error(f"Query processing failed: {e}")
            error_message = f"Error processing query: {str(e)}"
            yield "3:{text}\n".format(text=error_message)

    async def process_query(self, query: str, use_reranking: bool = True) -> str:
        """
        Process a query and return the complete response as a string.
        This is suitable for Django views that need the full response at once.

        Args:
            query: User's query
            use_reranking: Whether to use the reranking step

        Returns:
            Complete response text
        """
        full_response = ""
        response_started = False

        async for chunk in self.process_query_stream(query, use_reranking):
            # Extract text content from the chunk format
            if chunk.startswith('0:"'):
                # Extract content between quotes and handle escaping
                content = chunk[3:-2]  # Remove the '0:"' prefix and '"\n' suffix
                content = content.replace("\\n", "\n").replace('\\"', '"')

                # If this is the first chunk + separator
                if not response_started and "__LLM_RESPONSE__" in content:
                    # Only keep the part after the separator
                    parts = content.split("__LLM_RESPONSE__")
                    if len(parts) > 1:
                        content = parts[1]
                    response_started = True

                full_response += content

            elif chunk.startswith("3:"):
                # Error message
                error_content = chunk[2:]
                return f"Error: {error_content}"

        return full_response
