import os

from qdrant_client.http.models import ScoredPoint
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Conversation, Message
from .serializers import ConversationSerializer, MessageSerializer
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from typing import List
import logging

logger = logging.getLogger(__name__)


class ConversationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for handling conversations and chat functionality with vector search.
    """

    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]
    COLLECTION_NAME = "fishing_rules"

    # Singleton instances for expensive resources
    _embedding_model = None
    _qdrant_client = None

    @property
    def embedding_model(self):
        """Singleton property for the embedding model"""
        if self._embedding_model is None:
            try:
                self._embedding_model = SentenceTransformer("msmarco-bert-base-dot-v5")
            except Exception as e:
                logger.error(f"Failed to initialize embedding model: {e}")
                raise
        return self._embedding_model

    @property
    def qdrant_client(self):
        """Singleton property for the Qdrant client"""
        if self._qdrant_client is None:
            try:
                qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6334")
                self._qdrant_client = QdrantClient(url=qdrant_url)
            except Exception as e:
                logger.error(f"Failed to initialize Qdrant client: {e}")
                raise
        return self._qdrant_client

    def get_queryset(self):
        """Get conversations for the current user"""
        return Conversation.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """Create a new conversation for the current user"""
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        """Get all messages for a specific conversation"""
        conversation = self.get_object()
        messages = conversation.messages.all()
        serializer = MessageSerializer(messages, many=True)
        return Response(serializer.data)

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embeddings for the input text"""
        try:
            embedding = self.embedding_model.encode(text).tolist()
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise

    def perform_vector_search(
        self, embedding: List[float], limit: int = 3
    ) -> List[ScoredPoint]:
        """Perform vector search in Qdrant"""
        try:
            search_results = self.qdrant_client.search(
                collection_name=self.COLLECTION_NAME,
                query_vector=embedding,
                limit=limit,
            )
            return search_results
        except Exception as e:
            logger.error(f"Failed to perform vector search: {e}")
            raise

    def create_message(
        self, conversation, user, content: str, message_type: str
    ) -> Message:
        """Helper method to create a message"""
        try:
            return Message.objects.create(
                conversation=conversation,
                user=user,
                content=content,
                message_type=message_type,
            )
        except Exception as e:
            logger.error(f"Failed to create message: {e}")
            raise

    def process_search_results(self, search_results: List[ScoredPoint]) -> str:
        """Process search results into a response string"""
        if not search_results:
            return "No results found"

        response_parts = []
        for result in search_results:
            content = result.payload.get("content", "")
            if content:
                response_parts.append(content)

        return (
            "\n".join(response_parts)
            if response_parts
            else "No valid content found in results"
        )

    @action(detail=True, methods=["post"])
    def ask(self, request, pk=None):
        """
        Handle chat functionality with vector search

        Payload format:
        {
            "question": "user question text"
        }
        """
        conversation = self.get_object()
        question_text = request.data.get("question")

        if not question_text:
            return Response(
                {"error": "Question text is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Create user message
            user_message = self.create_message(
                conversation=conversation,
                user=request.user,
                content=question_text,
                message_type="user",
            )

            # Generate embedding
            embedding = self.generate_embedding(question_text)

            # Perform vector search
            search_results = self.perform_vector_search(embedding, limit=3)

            # Process search results
            response_content = self.process_search_results(search_results)

            # Create system message with response
            system_message = self.create_message(
                conversation=conversation,
                user=request.user,
                content=response_content,
                message_type="system",
            )

            return Response(
                {
                    "page_number": 0,
                    "response": response_content,
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            error_message = f"Error processing question: {str(e)}"
            logger.error(error_message)

            # Create error notification message
            try:
                self.create_message(
                    conversation=conversation,
                    user=request.user,
                    content=error_message,
                    message_type="notification",
                )
            except Exception as msg_error:
                logger.error(
                    f"Failed to create error notification message: {msg_error}"
                )

            return Response(
                {"error": error_message},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MessageViewSet(viewsets.ModelViewSet):
    """ViewSet for handling individual messages"""

    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Get messages for the current user"""
        return Message.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """Create a new message in the specified conversation"""
        conversation = get_object_or_404(
            Conversation,
            id=self.request.data.get("conversation"),
            user=self.request.user,
        )
        serializer.save(user=self.request.user, conversation=conversation)
