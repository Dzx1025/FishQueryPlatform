from django.db import models
from django.contrib.auth.models import User


class Conversation(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        help_text="The user who opened this conversation",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, help_text="The date and time this conversation was opened"
    )
    title = models.CharField(
        max_length=255, blank=True, help_text="The title of this conversation"
    )

    class Meta:
        ordering = ["-created_at"]


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, related_name="messages", on_delete=models.CASCADE
    )
    content = models.TextField(help_text="The content of the question or response")
    timestamp = models.DateTimeField(
        auto_now_add=True, help_text="The date and time this message was sent"
    )
    is_user_message = models.BooleanField(
        default=True, help_text="Whether the questions was sent by the users"
    )

    class Meta:
        ordering = ["timestamp"]
