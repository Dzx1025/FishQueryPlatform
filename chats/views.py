from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth import get_user_model
from .models import Chat, Message, MessageType
from .serializers import ChatRequestSerializer, ChatResponseSerializer, MessageSerializer
from .services import AIService
from .throttling import AnonymousUserRateThrottle, AuthenticatedUserRateThrottle

User = get_user_model()


def generate_title_from_message(message):
    """Generate a title from the user's message"""
    # Remove line breaks and extra spaces
    clean_message = ' '.join(message.split())

    # Truncate the message to a reasonable length
    if len(clean_message) > 50:
        title = clean_message[:50] + '...'
    else:
        title = clean_message

    return title


class ChatAPIView(APIView):
    """API endpoint for chat interactions"""
    permission_classes = [AllowAny]
    throttle_classes = [AnonymousUserRateThrottle, AuthenticatedUserRateThrottle]

    def post(self, request, chat_id=None):
        """Handle POST requests to create a new chat or add to existing chat"""
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        message_content = serializer.validated_data['message']

        # Determine the user (authenticated or anonymous)
        user = None
        if request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated:
            user = request.user
            # Check rate limiting for authenticated users
            if not user.can_send_message():
                return Response(
                    {"error": "Message limit reached. Please upgrade your plan."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

        # Get session ID for anonymous users
        session_id = None
        if not user:
            if hasattr(request, 'session') and request.session:
                if not request.session.session_key:
                    request.session.save()
                session_id = request.session.session_key
            if not session_id:
                session_id = request.META.get('REMOTE_ADDR', 'unknown')

        # CASE 1: If chat_id is provided, use existing chat
        if chat_id:
            try:
                if user:
                    chat = Chat.objects.get(id=chat_id, user=user)
                else:
                    chat = Chat.objects.get(id=chat_id, session_id=session_id)
            except Chat.DoesNotExist:
                return Response(
                    {"error": "Chat not found or you don't have permission to access it"},
                    status=status.HTTP_404_NOT_FOUND
                )
        # CASE 2: If no chat_id, create a new chat
        else:
            title = generate_title_from_message(message_content)
            if user:
                chat = Chat.objects.create(user=user, title=title)
            else:
                chat = Chat.objects.create(session_id=session_id, title=title)

        # Create user message
        user_message = Message.objects.create(
            chat=chat,
            content=message_content,
            message_type=MessageType.USER
        )

        # Generate AI response
        ai_service = AIService()
        ai_response = ai_service.generate_response(chat, message_content)

        # Create AI message
        assistant_message = Message.objects.create(
            chat=chat,
            content=ai_response,
            message_type=MessageType.ASSISTANT
        )

        # Update user message count if authenticated
        if user:
            user.increment_message_count()

        # Prepare response
        response_data = {
            'chat_id': chat.id,
            'title': chat.title,
            'user_message': user_message,
            'assistant_message': assistant_message
        }

        serializer = ChatResponseSerializer(response_data)
        return Response(serializer.data)

    def get(self, request, chat_id=None):
        """Handle GET requests to retrieve chat history"""
        # If no chat_id, return error
        if not chat_id:
            return Response(
                {"error": "Chat ID is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Determine the user (authenticated or anonymous)
        user = None
        if request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated:
            user = request.user

        # Get session ID for anonymous users
        session_id = None
        if not user:
            if hasattr(request, 'session') and request.session:
                session_id = request.session.session_key
            if not session_id:
                session_id = request.META.get('REMOTE_ADDR', 'unknown')

        # Retrieve the chat
        try:
            if user:
                chat = Chat.objects.get(id=chat_id, user=user)
            else:
                chat = Chat.objects.get(id=chat_id, session_id=session_id)
        except Chat.DoesNotExist:
            return Response(
                {"error": "Chat not found or you don't have permission to access it"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Retrieve all messages for this chat
        messages = chat.messages.all().order_by('created_at')

        # Serialize the messages
        message_serializer = MessageSerializer(messages, many=True)

        return Response({
            'chat_id': chat.id,
            'title': chat.title,
            'messages': message_serializer.data
        })
