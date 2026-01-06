import json
import hashlib
from datetime import timedelta
from uuid import UUID

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.cache import cache
from django.http import StreamingHttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from loguru import logger

from chats.utils import generate_title_from_message

from .models import Chat, Message, MessageType
from .services import get_ai_service, StreamEvent, StreamEventType

# --- Constants (from Django settings) ---
GlobalDailyMessageLimit = settings.CHAT_DAILY_MESSAGE_LIMIT
MessageMaxLength = settings.CHAT_MESSAGE_MAX_LENGTH


# --- Stream Formatters ---
class AISDKStreamFormatter:
    """
    Formatter for Vercel AI SDK UI Message Stream Protocol (SSE-based).

    Protocol uses Server-Sent Events with specific event types:
    - message-start: Begin new message
    - text-start/text-delta/text-end: Text streaming
    - source: Source documents for RAG citations
    - error: Error information
    - finish-message: Message completion
    - [DONE]: Stream termination

    See: https://sdk.vercel.ai/docs/ai-sdk-ui/stream-protocol
    """

    def __init__(self):
        self.message_id = f"msg-{id(self)}"
        self.text_id = f"text-{id(self)}"
        self.text_started = False

    def format_message_start(self) -> str:
        """Send message-start event."""
        data = json.dumps(
            {
                "type": "message-start",
                "value": {"id": self.message_id, "role": "assistant"},
            }
        )
        return f"event: message-start\ndata: {data}\n\n"

    def format_text_start(self) -> str:
        """Send text-start event."""
        data = json.dumps({"type": "text-start", "value": {"id": self.text_id}})
        return f"event: text-start\ndata: {data}\n\n"

    def format_text_delta(self, content: str) -> str:
        """Send text-delta event."""
        data = json.dumps(
            {"type": "text-delta", "value": {"id": self.text_id, "delta": content}}
        )
        return f"event: text-delta\ndata: {data}\n\n"

    def format_text_end(self) -> str:
        """Send text-end event."""
        data = json.dumps({"type": "text-end", "value": {"id": self.text_id}})
        return f"event: text-end\ndata: {data}\n\n"

    def format_source(self, source: dict) -> str:
        """Send source event for RAG citations."""
        data = json.dumps(
            {
                "type": "source",
                "value": {
                    "type": "source",
                    "sourceType": "document",
                    "id": f"source-{source['index']}",
                    "title": source.get("metadata", {}).get(
                        "title", f"Source {source['index']}"
                    ),
                    "document": {
                        "content": source["content"],
                        "metadata": source.get("metadata", {}),
                        "score": source.get("score", 0),
                        "index": source["index"],
                    },
                },
            }
        )
        return f"event: source\ndata: {data}\n\n"

    def format_error(self, error: str) -> str:
        """Send error event."""
        data = json.dumps({"type": "error", "value": {"message": error}})
        return f"event: error\ndata: {data}\n\n"

    def format_finish_message(self) -> str:
        """Send finish-message event."""
        data = json.dumps(
            {
                "type": "finish-message",
                "value": {"id": self.message_id, "finishReason": "stop"},
            }
        )
        return f"event: finish-message\ndata: {data}\n\n"

    def format_done(self) -> str:
        """Send [DONE] termination marker."""
        return "event: done\ndata: [DONE]\n\n"

    def format(self, event: StreamEvent) -> str:
        """Format a StreamEvent to AI SDK protocol."""
        result = ""

        match event.type:
            case StreamEventType.SOURCES:
                for source in event.data:
                    result += self.format_source(source)

            case StreamEventType.TEXT_DELTA:
                if not self.text_started:
                    result += self.format_message_start()
                    result += self.format_text_start()
                    self.text_started = True
                result += self.format_text_delta(event.data)

            case StreamEventType.DONE:
                if self.text_started:
                    result += self.format_text_end()
                result += self.format_finish_message()
                result += self.format_done()

            case StreamEventType.ERROR:
                result += self.format_error(event.data)
                result += self.format_done()

        return result


def format_sse_stream(event: StreamEvent, event_id: int) -> str:
    """
    Format StreamEvent to standard Server-Sent Events format.

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

        browser_fingerprint = request.headers.get("X-Browser-Fingerprint")
        if browser_fingerprint:
            return f"fp_{browser_fingerprint}"

        ip = request.META.get(
            "HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "unknown")
        )
        partial_ip = ".".join(ip.split(".")[:2])
        ua = request.META.get("HTTP_USER_AGENT", "")
        return f"ip_{hashlib.md5((partial_ip + ua).encode()).hexdigest()[:12]}"

    @staticmethod
    def get_user_or_identity(request):
        """Gets the authenticated user or stable device ID for anonymous users."""
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
    async def get_user_or_identity_async(request):
        """Async version: Gets the authenticated user or stable device ID for anonymous users."""
        user = getattr(request, "user", None)
        # Wrap the is_authenticated check in sync_to_async to avoid SynchronousOnlyOperation
        if user:
            is_auth = await sync_to_async(lambda: user.is_authenticated)()
            if is_auth:
                username = await sync_to_async(lambda: user.username)()
                logger.debug(
                    f"get_user_or_identity found authenticated user: {username}"
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
                max_age=settings.CHAT_DEVICE_COOKIE_MAX_AGE,
                httponly=True,
                samesite="Lax",
            )
        return response

    async def check_throttle_async(self, request):
        """Asynchronously checks message rate limits."""
        user, device_id = await self.get_user_or_identity_async(request)

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
    1. AI SDK UI Message Stream Protocol (X-Stream-Protocol: ai-sdk)
    2. Standard Server-Sent Events (default)

    Response includes:
    - Source documents for RAG citation lookup
    - Text chunks with inline [citation:N] markers
    - Completion signal
    """

    async def post(self, request, chat_id: UUID):
        allow, error_response = await self.check_throttle_async(request)
        if not allow:
            return error_response

        message_content, error_response = self.parse_request_data(request)
        if error_response:
            return error_response

        user, device_id = await self.get_user_or_identity_async(request)

        try:
            if user:
                chat = await Chat.objects.aget(id=chat_id, user=user)
            else:
                chat = await Chat.objects.aget(id=chat_id, session_id=device_id)
        except Chat.DoesNotExist:
            return JsonResponse(
                {"error": "Chat not found or permission denied."}, status=404
            )

        await Message.objects.acreate(
            chat=chat, content=message_content, message_type=MessageType.USER
        )
        if user and hasattr(user, "increment_message_count"):
            await sync_to_async(user.increment_message_count)()

        use_ai_sdk_format = request.headers.get("X-Stream-Protocol") == "ai-sdk"
        ai_service = get_ai_service()

        async def event_stream_generator():
            full_response_content = ""
            sources_data = None
            event_id = 1
            client_disconnected = False

            # Create formatter instance for AI SDK (maintains state)
            ai_sdk_formatter = AISDKStreamFormatter() if use_ai_sdk_format else None

            try:
                async for event in ai_service.process_query_stream(message_content):
                    if event.type == StreamEventType.SOURCES:
                        sources_data = event.data

                    if event.type == StreamEventType.TEXT_DELTA:
                        full_response_content += event.data

                    if use_ai_sdk_format:
                        yield ai_sdk_formatter.format(event)
                    else:
                        yield format_sse_stream(event, event_id)
                        event_id += 1

            except GeneratorExit:
                # Client disconnected (e.g., AbortController.abort() called)
                client_disconnected = True
                logger.info(f"Client disconnected during stream for chat {chat_id}")

            except Exception as e:
                error_str = str(e).lower()
                if "disconnect" in error_str or "closed" in error_str:
                    client_disconnected = True
                    logger.info(f"Client disconnected for chat {chat_id}: {e}")
                else:
                    logger.error(f"Streaming error for chat {chat_id}: {e}")
                    error_event = StreamEvent(type=StreamEventType.ERROR, data=str(e))
                    if use_ai_sdk_format:
                        yield ai_sdk_formatter.format(error_event)
                    else:
                        yield format_sse_stream(error_event, event_id)

            finally:
                # Save partial response even if client disconnected
                if full_response_content:
                    try:
                        metadata = {}
                        if sources_data:
                            metadata["sources"] = sources_data
                        if client_disconnected:
                            metadata["client_disconnected"] = True

                        await Message.objects.acreate(
                            chat=chat,
                            content=full_response_content,
                            message_type=MessageType.ASSISTANT,
                            metadata=metadata,
                        )
                        if client_disconnected:
                            logger.info(
                                f"Partial assistant message saved for chat {chat_id} (client disconnected)"
                            )
                        else:
                            logger.success(
                                f"Assistant message saved for chat {chat_id}"
                            )
                    except Exception as db_error:
                        logger.error(
                            f"Failed to save assistant message for chat {chat_id}: {db_error}"
                        )

        response = StreamingHttpResponse(
            event_stream_generator(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"

        return self.set_device_cookie_if_needed(request, response, device_id, user)
