# chats/urls.py
from django.urls import path
from .views import ChatAPIView

urlpatterns = [
    # This will handle both creating a new chat (without sessionid)
    # and adding to existing chat (with sessionid)
    path('', ChatAPIView.as_view(), name='chat_create'),
    path('<uuid:chat_id>/', ChatAPIView.as_view(), name='chat_message'),
]
