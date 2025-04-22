import asyncio
import json
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.http import StreamingHttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import Chat, Message, MessageType
from .services import AIService

DailyMessageLimit = 30


def generate_title_from_message(message):
    clean_message = ' '.join(message.split())
    return clean_message[:20] + '...' if len(clean_message) > 20 else clean_message


class ChatBaseView(View):
    @staticmethod
    async def parse_request_data(request):
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

    @staticmethod
    async def get_user_or_identity(request):
        """Get authenticated user or session ID."""

        if hasattr(request, 'user') and request.user is not None:
            # wrapped in sync_to_async to avoid async context errors
            is_authenticated = await sync_to_async(lambda u: getattr(u, 'is_authenticated', False))(request.user)
            if is_authenticated:
                return request.user, None

        # For anonymous users
        device_id = request.COOKIES.get('device_id')

        # If device ID is not found in cookies, try to get it from headers
        if not device_id:
            browser_fingerprint = request.headers.get('X-Browser-Fingerprint')
            if browser_fingerprint:
                device_id = f"fp_{browser_fingerprint}"

        # Finally, if device ID is not found in cookies, session, or headers, generate it from IP and user agent
        if not device_id:
            ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', 'unknown'))
            # Only use the first two parts of the IP address
            ip_parts = ip.split('.')
            partial_ip = '.'.join(ip_parts[:2]) if len(ip_parts) >= 2 else ip

            user_agent = request.META.get('HTTP_USER_AGENT', '')

            import hashlib
            # Create a hash from the partial IP and user agent
            device_id = f"ip_{hashlib.md5((partial_ip + user_agent).encode()).hexdigest()[:12]}"

        return None, device_id

    async def check_throttle(self, request):
        """Check if the request should be throttled."""
        # Get user or session
        user, session_id = await self.get_user_or_identity(request)

        if user:
            # For authenticated users, use the model's can_send_message
            can_proceed = user.can_send_message()
            if not can_proceed:
                return False, JsonResponse({"error": "Message limit reached. Please upgrade your plan."}, status=429)
        else:
            # For anonymous users, implement manual throttling since DRF throttling might not work well in Django views
            cache_key = f"throttle_{session_id}"
            now = timezone.now()

            # Check if this key exists in cache
            hit_count = cache.get(cache_key, None)

            if hit_count is None:
                # First request from this device
                cache.set(cache_key, 1, 86400)  # 24 hours (day)
                allow = True
                wait_time = None
            elif hit_count >= DailyMessageLimit:  # Exceeded the limit
                # Rate limit exceeded
                allow = False
                # Calculate time until reset (end of the day)
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                wait_time = int((tomorrow - now).total_seconds())
            else:
                # Increment the counter
                cache.set(cache_key, hit_count + 1, None)  # Keep the existing expiry
                allow = True
                wait_time = None

            if not allow:
                response = JsonResponse({"error": "Rate limit exceeded. Try again later."}, status=429)
                if wait_time:
                    response['Retry-After'] = wait_time
                return False, response

        return True, None


@method_decorator(csrf_exempt, name='dispatch')
class ChatCreateView(ChatBaseView):
    async def post(self, request):
        try:
            # Check throttling
            allow, error_response = await self.check_throttle(request)
            if not allow:
                return error_response

            # Parse request data
            message_content, error_response = await self.parse_request_data(request)
            if error_response:
                return error_response

            # Get user or session
            user, device_id = await self.get_user_or_identity(request)

            # Create a new chat with title from message
            title = generate_title_from_message(message_content)
            chat = await Chat.objects.acreate(user=user, title=title) if user else await Chat.objects.acreate(
                session_id=device_id, title=title)

            # Return the chat ID and set device_id cookie if needed
            response = JsonResponse({"chat_id": str(chat.id)})

            # Set device_id cookie for future identification if it was generated in this request
            if not request.COOKIES.get('device_id') and not user:
                # Set cookie to expire in 1 year
                max_age = 365 * 24 * 60 * 60  # 1 year in seconds
                response.set_cookie('device_id', device_id, max_age=max_age, httponly=True, samesite='Lax')

            return response

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ChatMessageView(ChatBaseView):
    async def post(self, request, chat_id):
        try:
            # Check throttling
            allow, error_response = await self.check_throttle(request)
            if not allow:
                return error_response

            # Parse request data
            message_content, error_response = await self.parse_request_data(request)
            if error_response:
                return error_response

            # Get user or session
            user, device_id = await self.get_user_or_identity(request)

            # Get chat
            try:
                chat = await Chat.objects.aget(id=chat_id, user=user) if user else await Chat.objects.aget(id=chat_id,
                                                                                                           session_id=device_id)

            except Chat.DoesNotExist:
                return JsonResponse({"error": "Chat not found or you don't have permission to access it"}, status=404)

            # Save user question
            await Message.objects.acreate(chat=chat, content=message_content, message_type=MessageType.USER)

            if user:
                user.increment_message_count()

            # Stream response from AI service using SSE format
            ai_service = AIService()

            async def sse_generator():
                full_response = ""  # Accumulator for the full response
                event_id = 1  # Start with event ID 1

                # Send a start event
                yield f"id: {event_id}\n"
                yield f"event: start\n"
                yield f"data: {{}}\n\n"
                event_id += 1

                try:
                    async for chunk in ai_service.process_query_stream(message_content):
                        full_response += chunk  # Accumulate the response

                        yield f"id: {event_id}\n"
                        yield f"event: message\n"
                        yield f"data: {json.dumps({'content': chunk})}\n\n"
                        event_id += 1

                        await asyncio.sleep(0)

                    # Save assistant response after streaming is complete
                    await Message.objects.acreate(chat=chat, content=full_response, message_type=MessageType.ASSISTANT)

                    # Send a done event
                    yield f"id: {event_id}\n"
                    yield f"event: done\n"
                    yield f"data: {{}}\n\n"

                except Exception as ex:
                    error_msg = f"Error: {str(ex)}"

                    # Send error as an SSE event
                    yield f"id: {event_id}\n"
                    yield f"event: error\n"
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"

                    # Save error message
                    await Message.objects.acreate(chat=chat, content=error_msg, message_type=MessageType.ASSISTANT)

            # Create response with correct content type for SSE
            response = StreamingHttpResponse(
                sse_generator(),
                content_type="text/event-stream"
            )

            # Important headers for SSE
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'  # For Nginx
            # response['Connection'] = 'keep-alive'
            # Set device_id cookie for future identification if it was generated in this request
            if not request.COOKIES.get('device_id') and not user:
                # Set cookie to expire in 1 year
                max_age = 365 * 24 * 60 * 60  # 1 year in seconds
                response.set_cookie('device_id', device_id, max_age=max_age, httponly=True, samesite='Lax')

            return response

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
