from django.db import models
from django.contrib.auth.models import User


class Conversation(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conversations",
        help_text="The user in this conversation",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, help_text="When this conversation was created"
    )
    title = models.CharField(
        max_length=255, blank=True, help_text="Title of the conversation"
    )

    class Meta:
        ordering = ["-created_at"]


class Message(models.Model):
    MESSAGE_TYPES = [
        ("user", "User Message"),
        ("system", "System Message"),
        ("notification", "Notification"),
    ]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        help_text="The conversation this message belongs to",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="messages",
        help_text="The user in this conversation",
    )
    content = models.TextField(help_text="The content of the message")
    timestamp = models.DateTimeField(
        auto_now_add=True, help_text="When this message was sent"
    )
    message_type = models.CharField(
        max_length=20,
        choices=MESSAGE_TYPES,
        default="user",
        help_text="The type of this message",
    )

    class Meta:
        ordering = ["timestamp"]
