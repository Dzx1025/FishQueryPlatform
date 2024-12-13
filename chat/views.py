from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from chat.models import Conversation, Message
from chat.serializers import (
    ConversationSerializer,
    MessageSerializer,
    MessageCreateSerializer,
)


class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Conversation.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def send_message(self, request, pk=None):
        conversation = self.get_object()
        serializer = MessageCreateSerializer(data=request.data)

        if serializer.is_valid():
            message = Message.objects.create(
                conversation=conversation,
                content=serializer.validated_data["content"],
                is_user_message=True,
            )

            # Here you can add your chatbot logic to generate a response
            # For example:
            bot_response = self.generate_bot_response(message.content)
            bot_message = Message.objects.create(
                conversation=conversation, content=bot_response, is_user_message=False
            )

            return Response(MessageSerializer(bot_message).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def generate_bot_response(self, user_message):
        # Add your chatbot logic here
        # This is a simple example - replace with your actual implementation
        return f"You said: {user_message}. This is a placeholder response."
