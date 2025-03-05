from rest_framework import serializers
from .models import Chat, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['content', 'message_type', 'created_at']
        read_only_fields = ['message_type', 'created_at']


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(required=True)
