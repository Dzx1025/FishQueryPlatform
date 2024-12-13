from django.contrib import admin
from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("timestamp",)
    fields = ("content", "is_user_message", "timestamp")
    can_delete = False
    max_num = 0  # Prevents adding new messages from admin


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "created_at", "message_count")
    list_filter = ("created_at", "user")
    search_fields = ("title", "user__username", "messages__content")
    readonly_fields = ("created_at",)
    inlines = [MessageInline]

    def message_count(self, obj):
        return obj.messages.count()

    message_count.short_description = "Number of Messages"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "conversation",
        "truncated_content",
        "is_user_message",
        "timestamp",
    )
    list_filter = ("is_user_message", "timestamp", "conversation")
    search_fields = ("content", "conversation__title")
    readonly_fields = ("timestamp",)

    def truncated_content(self, obj):
        return obj.content[:100] + "..." if len(obj.content) > 100 else obj.content

    truncated_content.short_description = "Content"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("conversation", "conversation__user")
        )
