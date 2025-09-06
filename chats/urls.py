# chats/urls.py
from django.urls import path
from .views import ChatCreateView, ChatMessageView

urlpatterns = [
    # This path creates a new chat and returns the chat_id
    path("", ChatCreateView.as_view(), name="chat_create"),
    # This path handles messages for an existing chat
    path("<uuid:chat_id>/", ChatMessageView.as_view(), name="chat_message"),
]
