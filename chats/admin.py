from django.contrib import admin
from .models import Chat, Message


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "session_id", "created_at", "updated_at")
    list_filter = ("created_at",)
    search_fields = ("title", "user__username", "user__email", "session_id")
    date_hierarchy = "created_at"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "chat", "message_type", "short_content", "created_at")
    list_filter = ("message_type", "created_at")
    search_fields = (
        "content",
        "chat__title",
        "chat__user__username",
        "chat__session_id",
    )
    date_hierarchy = "created_at"

    def short_content(self, obj):
        return obj.content[:50] + ("..." if len(obj.content) > 50 else "")

    short_content.short_description = "Content"
