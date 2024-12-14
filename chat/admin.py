from django.contrib import admin
from .models import Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "created_at")
    list_filter = ("created_at", "user")
    search_fields = ("title", "user__username")
    ordering = ("-created_at",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "user", "message_type", "timestamp")
    list_filter = ("message_type", "timestamp", "user")
    search_fields = ("content", "user__username", "conversation__title")
    ordering = ("timestamp",)
