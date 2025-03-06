import asyncio
import json

from asgiref.sync import sync_to_async
from django.http import StreamingHttpResponse, JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import AllowAny

from .models import Chat, Message, MessageType
from .services import AIService
from .throttling import AnonymousUserRateThrottle, AuthenticatedUserRateThrottle

get_chat = sync_to_async(Chat.objects.get)
create_chat = sync_to_async(Chat.objects.create)
create_message = sync_to_async(Message.objects.create)
can_send_message = sync_to_async(lambda user: user.can_send_message())
increment_message_count = sync_to_async(lambda user: user.increment_message_count())


def generate_title_from_message(message):
    clean_message = ' '.join(message.split())
    return clean_message[:20] + '...' if len(clean_message) > 20 else clean_message


class ChatBaseView(View):
    permission_classes = [AllowAny]
    throttle_classes = [AnonymousUserRateThrottle, AuthenticatedUserRateThrottle]

    async def parse_request_data(self, request):
        """Parse and validate request data."""
        try:
            data = json.loads(request.body)
            message_content = data.get('message')

            if not message_content:
                return None, JsonResponse({"error": "Message is required"}, status=400)
            elif len(message_content) > 200:
                return None, JsonResponse({"error": "Message is too long"}, status=400)

            return message_content, None
        except json.JSONDecodeError:
            return None, JsonResponse({"error": "Invalid JSON"}, status=400)

    async def get_user_or_session(self, request):
        """Get authenticated user or session ID."""
        # User authentication - wrapped in sync_to_async to avoid async context errors
        user = None

        if hasattr(request, 'user') and request.user is not None:
            # Safely check authentication status in a sync context
            is_authenticated = await sync_to_async(lambda u: getattr(u, 'is_authenticated', False))(request.user)
            if is_authenticated:
                user = request.user

        # Session ID for anonymous users
        session_id = None
        if not user:
            if hasattr(request, 'session') and request.session:
                if not request.session.session_key:
                    await sync_to_async(request.session.save)()
                session_id = request.session.session_key
            if not session_id:
                session_id = request.META.get('REMOTE_ADDR', 'unknown')

        return user, session_id


@method_decorator(csrf_exempt, name='dispatch')
class ChatCreateView(ChatBaseView):
    async def post(self, request):
        try:
            # Parse request data
            message_content, error_response = await self.parse_request_data(request)
            if error_response:
                return error_response

            # Get user or session
            user, session_id = await self.get_user_or_session(request)

            # Create a new chat with title from message
            title = generate_title_from_message(message_content)
            chat = await create_chat(user=user, title=title) if user else await create_chat(session_id=session_id,
                                                                                            title=title)

            # Return the chat ID
            return JsonResponse({"chat_id": str(chat.id)})

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ChatMessageView(ChatBaseView):
    async def post(self, request, chat_id):
        try:
            # Parse request data
            message_content, error_response = await self.parse_request_data(request)
            if error_response:
                return error_response

            # Get user or session
            user, session_id = await self.get_user_or_session(request)

            # Check message limit for authenticated users
            if user and not await can_send_message(user):
                return JsonResponse({"error": "Message limit reached. Please upgrade your plan."}, status=429)

            # Get chat
            try:
                chat = await get_chat(id=chat_id, user=user) if user else await get_chat(id=chat_id,
                                                                                         session_id=session_id)
            except Chat.DoesNotExist:
                return JsonResponse({"error": "Chat not found or you don't have permission to access it"}, status=404)

            # No need to update title as it's already set during chat creation

            # Save user question
            await create_message(chat=chat, content=message_content, message_type=MessageType.USER)

            if user:
                await increment_message_count(user)

            # Stream response from AI service
            ai_service = AIService()

            async def stream_generator():
                full_response = ""  # Move to the beginning of the function as an accumulator
                try:
                    async for chunk in ai_service.process_query_stream(message_content):
                        # Process based on the actual output format of your AI service
                        if chunk.startswith('0:"'):
                            # Extract content between quotes and handle escaping
                            content = chunk[3:-2]  # Remove the '0:"' prefix and '"\n' suffix
                            content = content.replace('\\n', '\n').replace('\\"', '"')
                            full_response += content  # Accumulate the response
                            yield content

                        await asyncio.sleep(0)

                    # Save assistant response
                    await create_message(chat=chat, content=full_response, message_type=MessageType.ASSISTANT)
                except Exception as ex:
                    error_msg = f"Error: {str(ex)}"
                    yield error_msg
                    # Save error message
                    await create_message(chat=chat, content=error_msg, message_type=MessageType.ASSISTANT)

            return StreamingHttpResponse(stream_generator(), content_type="text/plain")

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
