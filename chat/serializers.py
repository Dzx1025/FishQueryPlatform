from rest_framework import serializers
from .models import Conversation, Message
from django.contrib.auth.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username")


class MessageSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ("id", "conversation", "user", "content", "timestamp", "message_type")
        read_only_fields = ("timestamp",)


def get_last_message(obj):
    last_message = obj.messages.last()
    if last_message:
        return MessageSerializer(last_message).data
    return None


def get_message_count(obj):
    return obj.messages.count()


class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    user = UserSerializer(read_only=True)
    message_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = (
            "id",
            "user",
            "created_at",
            "messages",
            "message_count",
            "last_message",
        )
        read_only_fields = ("created_at",)
