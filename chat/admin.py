from django.contrib import admin
from django.contrib.auth.models import User
from .models import Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "created_at")
    list_filter = ("created_at", "user")
    search_fields = ("user__username",)
    ordering = ("-created_at",)
    autocomplete_fields = ["user"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "conversation_id",
        "user",
        "message_type",
        "timestamp",
        "short_content",
    )
    list_filter = ("message_type", "timestamp", "user")
    search_fields = ("content", "user__username")
    ordering = ("timestamp",)
    autocomplete_fields = ["conversation", "user"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "conversation")

    def conversation_id(self, obj):
        return f"Conversation #{obj.conversation.id}"

    conversation_id.short_description = "Conversation"

    def short_content(self, obj):
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content

    short_content.short_description = "Content"
