import asyncio
import json
import hashlib
from datetime import timedelta
from uuid import UUID

from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.http import StreamingHttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from loguru import logger

from chats.utils import generate_title_from_message

from .models import Chat, Message, MessageType
from .services import AIService

# --- Constants ---
GlobalDailyMessageLimit = 30
MessageMaxLength = 200
DeviceCookieMaxAge = 365 * 24 * 60 * 60  # 1 year in seconds


# --- Base View with Shared Logic ---
class ChatBaseView(View):
    """
    Base view containing shared logic for parsing, identity management,
    throttling, and cookie handling.
    """

    @staticmethod
    def _get_device_id(request) -> str:
        """Generates a stable device ID for anonymous users."""
        device_id = request.COOKIES.get("device_id")
        if device_id:
            return device_id

        # Fallback to browser fingerprint header
        browser_fingerprint = request.headers.get("X-Browser-Fingerprint")
        if browser_fingerprint:
            return f"fp_{browser_fingerprint}"

        # Last resort: generate from IP and User-Agent
        ip = request.META.get(
            "HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "unknown")
        )
        partial_ip = ".".join(ip.split(".")[:2])  # Use partial IP for privacy
        ua = request.META.get("HTTP_USER_AGENT", "")
        return f"ip_{hashlib.md5((partial_ip + ua).encode()).hexdigest()[:12]}"

    @staticmethod
    def get_user_or_identity(request):
        """
        Gets the authenticated user. If the user is anonymous, returns a stable device ID.
        This method is purely computational and does not perform I/O.
        """
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            logger.debug(
                f"get_user_or_identity found authenticated user: {user.username}"
            )
            return user, None

        device_id = ChatBaseView._get_device_id(request)
        logger.debug(
            f"get_user_or_identity found anonymous user, device_id: {device_id}"
        )
        return None, device_id

    @staticmethod
    def parse_request_data(request):
        """Parses and validates message content from the request body."""
        try:
            data = json.loads(request.body)
            message_content = data.get("message")
            if not message_content:
                return None, JsonResponse({"error": "Message is required"}, status=400)
            if len(message_content) > MessageMaxLength:
                return None, JsonResponse(
                    {"error": f"Message cannot exceed {MessageMaxLength} characters"},
                    status=400,
                )
            return message_content, None
        except json.JSONDecodeError:
            return None, JsonResponse({"error": "Invalid JSON"}, status=400)

    @staticmethod
    def set_device_cookie_if_needed(request, response, device_id: str, user):
        """Attaches the device_id cookie to the response if it's a new anonymous user."""
        if not user and not request.COOKIES.get("device_id"):
            response.set_cookie(
                "device_id",
                device_id,
                max_age=DeviceCookieMaxAge,
                httponly=True,
                samesite="Lax",
            )
        return response

    async def check_throttle_async(self, request):
        """
        Asynchronously checks message rate limits for both authenticated and anonymous users.
        Uses atomic cache operations for anonymous users to prevent race conditions.
        """
        user, device_id = self.get_user_or_identity(request)

        if user:
            # For authenticated users, delegate to the user model's method.
            # Convert the sync method to async.
            can_send = await sync_to_async(user.can_send_message)()
            if not can_send:
                return False, JsonResponse(
                    {"error": "Message limit reached. Please upgrade your plan."},
                    status=429,
                )
        else:
            # For anonymous users, use atomic cache operations.
            cache_key = f"throttle_{device_id}"
            try:
                # Atomically increment the count.
                hit_count = await cache.aincr(cache_key)

                # If it's the first hit, set the expiry for 24 hours.
                if hit_count == 1:
                    await cache.aexpire(cache_key, timeout=86400)

                if hit_count > GlobalDailyMessageLimit:
                    now = timezone.now()
                    tomorrow = now.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ) + timedelta(days=1)
                    wait_time = int((tomorrow - now).total_seconds())

                    resp = JsonResponse(
                        {
                            "error": "Daily message limit reached for anonymous users. Please log in for a higher limit."
                        },
                        status=429,
                    )
                    resp["Retry-After"] = wait_time
                    return False, resp
            except Exception as e:
                logger.error(f"Cache throttling error: {e}")
                # Fail open: if cache fails, allow the request but log the error.
                pass

        return True, None


# --- Views ---
@method_decorator(csrf_exempt, name="dispatch")
class ChatCreateView(ChatBaseView):
    """
    Handles the creation of a new chat session.
    This view can remain synchronous as it performs simple, fast database writes.
    """

    def post(self, request):
        allow, error_response = self.check_throttle(request)
        if not allow:
            return error_response

        message_content, error_response = self.parse_request_data(request)
        if error_response:
            return error_response

        user, device_id = self.get_user_or_identity(request)
        title = generate_title_from_message(message_content)

        try:
            if user:
                chat = Chat.objects.create(user=user, title=title)
            else:
                chat = Chat.objects.create(session_id=device_id, title=title)
        except Exception as e:
            logger.error(f"Error creating chat: {e}")
            return JsonResponse({"error": "Could not create chat session."}, status=500)

        response = JsonResponse({"chat_id": str(chat.id)})
        return self.set_device_cookie_if_needed(request, response, device_id, user)

    # We need a sync version of check_throttle for this sync view.
    # It's less performant but necessary if we keep this view synchronous.
    def check_throttle(self, request):
        user, device_id = self.get_user_or_identity(request)
        if user:
            if not user.can_send_message():
                return False, JsonResponse(
                    {"error": "Message limit reached. Please upgrade your plan."},
                    status=429,
                )
        else:
            cache_key = f"throttle_{device_id}"
            hit_count = cache.get(cache_key, 0)
            if hit_count >= GlobalDailyMessageLimit:
                return False, JsonResponse(
                    {"error": "Daily limit reached."}, status=429
                )
            cache.set(cache_key, hit_count + 1, 86400)
        return True, None


@method_decorator(csrf_exempt, name="dispatch")
class ChatMessageView(ChatBaseView):
    """
    Handles sending a message to an existing chat and streams the AI response.
    This view is fully asynchronous.
    """

    async def post(self, request, chat_id: UUID):
        # 1. Perform pre-flight checks asynchronously
        allow, error_response = await self.check_throttle_async(request)
        if not allow:
            return error_response

        message_content, error_response = self.parse_request_data(request)
        if error_response:
            return error_response

        user, device_id = self.get_user_or_identity(request)
        # 2. Retrieve the chat object asynchronously
        try:
            if user:
                chat = await Chat.objects.aget(id=chat_id, user=user)
            else:
                chat = await Chat.objects.aget(id=chat_id, session_id=device_id)
        except Chat.DoesNotExist:
            return JsonResponse(
                {"error": "Chat not found or permission denied."}, status=404
            )

        # 3. Save the user's message asynchronously
        await Message.objects.acreate(
            chat=chat, content=message_content, message_type=MessageType.USER
        )
        if user and hasattr(user, "increment_message_count"):
            await sync_to_async(user.increment_message_count)()

        # 4. Define the async generator for the AI response stream
        ai_service = AIService()

        async def event_stream_generator():
            full_response_content = ""
            event_id = 1
            try:
                # Initial "start" event
                yield f"id: {event_id}\nevent: start\ndata: {{}}\n\n"
                event_id += 1

                # Stream AI response chunks
                async for chunk in ai_service.process_query_stream(message_content):
                    logger.debug(f"Chunk: {chunk}")
                    full_response_content += chunk
                    data = json.dumps({"content": chunk})
                    yield f"id: {event_id}\nevent: message\ndata: {data}\n\n"
                    event_id += 1
                    await asyncio.sleep(
                        0.01
                    )  # Small sleep to ensure chunks are sent timely

                # Final "done" event
                yield f"id: {event_id}\nevent: done\ndata: {{}}\n\n"

            except Exception as e:
                logger.error(f"AI streaming error for chat {chat_id}: {e}")
                error_data = json.dumps(
                    {"error": "An error occurred during streaming."}
                )
                yield f"id: {event_id+1}\nevent: error\ndata: {error_data}\n\n"
            finally:
                # CRITICAL: Save the full response to the database after the stream is complete.
                if full_response_content:
                    try:
                        await Message.objects.acreate(
                            chat=chat,
                            content=full_response_content,
                            message_type=MessageType.ASSISTANT,
                        )
                        logger.success(f"Assistant message saved for chat {chat_id}")
                    except Exception as db_error:
                        logger.error(
                            f"Failed to save assistant message for chat {chat_id}: {db_error}"
                        )

        # 5. Create and configure the StreamingHttpResponse
        response = StreamingHttpResponse(
            event_stream_generator(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # Necessary for Nginx

        # 6. Set cookie if needed and return response
        return self.set_device_cookie_if_needed(request, response, device_id, user)
