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
from .services import AIService, StreamEvent, StreamEventType

# --- Constants ---
GlobalDailyMessageLimit = 30
MessageMaxLength = 200
DeviceCookieMaxAge = 365 * 24 * 60 * 60  # 1 year in seconds


# --- Stream Formatters ---
def format_ai_sdk_stream(event: StreamEvent) -> str:
    """
    Format StreamEvent to Vercel AI SDK Data Stream Protocol.

    Protocol format: TYPE:VALUE\n
    - 0: Text chunk (value must be JSON string)
    - 2: Data chunk (value is JSON array) - used for sources
    - d: Done signal (value is JSON object)
    - 3: Error (value is JSON string)

    Frontend can parse [citation:N] markers in text and lookup source by index.
    """
    match event.type:
        case StreamEventType.SOURCES:
            # Type 2: Data chunk for sources array
            # Frontend uses this to build citation lookup map
            return f"2:{json.dumps([{'sources': event.data}])}\n"

        case StreamEventType.TEXT_DELTA:
            # Type 0: Text chunk with potential [citation:N] markers
            return f"0:{json.dumps(event.data)}\n"

        case StreamEventType.DONE:
            return f"d:{json.dumps(event.data)}\n"

        case StreamEventType.ERROR:
            return f"3:{json.dumps(event.data)}\n"

        case _:
            return ""


def format_sse_stream(event: StreamEvent, event_id: int) -> str:
    """
    Format StreamEvent to standard Server-Sent Events format.

    SSE format:
    id: <event_id>
    event: <event_type>
    data: <json_data>

    Event types:
    - sources: Array of source documents for citation lookup
    - message: Text chunk (may contain [citation:N] markers)
    - done: Stream complete
    - error: Error occurred
    """
    match event.type:
        case StreamEventType.SOURCES:
            data = json.dumps({"sources": event.data})
            return f"id: {event_id}\nevent: sources\ndata: {data}\n\n"

        case StreamEventType.TEXT_DELTA:
            data = json.dumps({"content": event.data})
            return f"id: {event_id}\nevent: message\ndata: {data}\n\n"

        case StreamEventType.DONE:
            data = json.dumps(event.data)
            return f"id: {event_id}\nevent: done\ndata: {data}\n\n"

        case StreamEventType.ERROR:
            data = json.dumps({"error": event.data})
            return f"id: {event_id}\nevent: error\ndata: {data}\n\n"

        case _:
            return ""


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
        partial_ip = ".".join(ip.split(".")[:2])
        ua = request.META.get("HTTP_USER_AGENT", "")
        return f"ip_{hashlib.md5((partial_ip + ua).encode()).hexdigest()[:12]}"

    @staticmethod
    def get_user_or_identity(request):
        """
        Gets the authenticated user. If the user is anonymous, returns a stable device ID.
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
            can_send = await sync_to_async(user.can_send_message)()
            if not can_send:
                return False, JsonResponse(
                    {"error": "Message limit reached. Please upgrade your plan."},
                    status=429,
                )
        else:
            cache_key = f"throttle_{device_id}"
            try:
                hit_count = await cache.aincr(cache_key)

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
                pass

        return True, None


# --- Views ---
@method_decorator(csrf_exempt, name="dispatch")
class ChatCreateView(ChatBaseView):
    """Handles the creation of a new chat session."""

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

    def check_throttle(self, request):
        """Synchronous throttle check for sync views."""
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

    Supports two stream protocols:
    1. AI SDK Data Stream Protocol (X-Stream-Protocol: ai-sdk)
    2. Standard Server-Sent Events (default)

    Response format:
    - First event: sources array for citation lookup
    - Following events: text chunks with inline [citation:N] markers
    - Final event: done signal

    Frontend should:
    1. Store sources from first event
    2. Parse [citation:N] in text and render as clickable links
    3. Lookup source details by index when user clicks citation
    """

    async def post(self, request, chat_id: UUID):
        # Pre-flight checks
        allow, error_response = await self.check_throttle_async(request)
        if not allow:
            return error_response

        message_content, error_response = self.parse_request_data(request)
        if error_response:
            return error_response

        user, device_id = self.get_user_or_identity(request)

        # Retrieve chat object
        try:
            if user:
                chat = await Chat.objects.aget(id=chat_id, user=user)
            else:
                chat = await Chat.objects.aget(id=chat_id, session_id=device_id)
        except Chat.DoesNotExist:
            return JsonResponse(
                {"error": "Chat not found or permission denied."}, status=404
            )

        # Save user message
        await Message.objects.acreate(
            chat=chat, content=message_content, message_type=MessageType.USER
        )
        if user and hasattr(user, "increment_message_count"):
            await sync_to_async(user.increment_message_count)()

        # Determine stream format based on client header
        use_ai_sdk_format = request.headers.get("X-Stream-Protocol") == "ai-sdk"

        ai_service = AIService()

        async def event_stream_generator():
            full_response_content = ""
            sources_data = None
            event_id = 1

            try:
                async for event in ai_service.process_query_stream(message_content):
                    # Collect sources for database persistence
                    if event.type == StreamEventType.SOURCES:
                        sources_data = event.data

                    # Collect text for database persistence
                    if event.type == StreamEventType.TEXT_DELTA:
                        full_response_content += event.data

                    # Format and yield based on protocol
                    if use_ai_sdk_format:
                        yield format_ai_sdk_stream(event)
                    else:
                        yield format_sse_stream(event, event_id)
                        event_id += 1

            except Exception as e:
                logger.error(f"Streaming error for chat {chat_id}: {e}")
                error_event = StreamEvent(type=StreamEventType.ERROR, data=str(e))
                if use_ai_sdk_format:
                    yield format_ai_sdk_stream(error_event)
                else:
                    yield format_sse_stream(error_event, event_id)

            finally:
                # Persist assistant response with sources to database
                if full_response_content:
                    try:
                        metadata = {}
                        if sources_data:
                            metadata["sources"] = sources_data

                        await Message.objects.acreate(
                            chat=chat,
                            content=full_response_content,
                            message_type=MessageType.ASSISTANT,
                            metadata=metadata,
                        )
                        logger.success(f"Assistant message saved for chat {chat_id}")
                    except Exception as db_error:
                        logger.error(
                            f"Failed to save assistant message for chat {chat_id}: {db_error}"
                        )

        # Configure response based on format
        if use_ai_sdk_format:
            content_type = "text/plain; charset=utf-8"
        else:
            content_type = "text/event-stream"

        response = StreamingHttpResponse(
            event_stream_generator(), content_type=content_type
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"

        return self.set_device_cookie_if_needed(request, response, device_id, user)
