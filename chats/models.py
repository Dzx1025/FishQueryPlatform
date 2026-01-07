import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Chat(models.Model):
    """Model representing a chat session"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=100, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chats",
        null=True,
        blank=True,
    )
    session_id = models.CharField(
        max_length=100, blank=True, null=True
    )  # For anonymous users
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.title:
            return self.title
        if self.user:
            return f"Chat - {self.user.username}"
        return f"Chat - Anonymous ({self.session_id})"

    class Meta:
        ordering = ["-updated_at"]


class MessageType(models.TextChoices):
    """Enum for message types"""

    USER = "user", _("User")
    ASSISTANT = "assistant", _("Assistant")


class Message(models.Model):
    """Model representing a message in a chat"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    content = models.TextField()
    message_type = models.CharField(
        max_length=10,
        choices=MessageType.choices,
        default=MessageType.USER,
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional data such as sources for assistant messages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.message_type}: {self.content[:30]}{'...' if len(self.content) > 30 else ''}"

    class Meta:
        ordering = ["created_at"]
