from rest_framework import serializers
from .models import Chat, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['content', 'message_type', 'created_at']
        read_only_fields = ['message_type', 'created_at']


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(required=True)


class ChatResponseSerializer(serializers.Serializer):
    chat_id = serializers.UUIDField()
    title = serializers.CharField()
    user_message = MessageSerializer()
    assistant_message = MessageSerializer()


class ChatHistorySerializer(serializers.Serializer):
    chat_id = serializers.UUIDField()
    title = serializers.CharField()
    messages = MessageSerializer(many=True)
