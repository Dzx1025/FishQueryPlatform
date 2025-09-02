import asyncio
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from loguru import logger
from asgiref.sync import sync_to_async


def get_user_from_jwt_token_sync(request):
    token = request.COOKIES.get(settings.SIMPLE_JWT.get("AUTH_COOKIE"))
    if not token:
        return getattr(request, "user", AnonymousUser())
    request.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    auth = JWTAuthentication()
    try:
        user_auth_tuple = auth.authenticate(request)
        if user_auth_tuple:
            user, _ = user_auth_tuple
            return user
        return AnonymousUser()
    except Exception as e:
        logger.warning(f"JWT authentication failed: {e}")
        return AnonymousUser()


class JWTCookieMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.get_user_async = sync_to_async(
            get_user_from_jwt_token_sync, thread_sensitive=True
        )

    def __call__(self, request):
        # Admin uses its own session authentication, our JWT logic should not intervene
        if request.path.startswith("/admin/"):
            return self.get_response(request)

        if asyncio.iscoroutinefunction(self.get_response):
            return self.acall_logic(request)

        # Handle other synchronous requests (if any)
        request.user = get_user_from_jwt_token_sync(request)
        return self.get_response(request)

    async def acall_logic(self, request):
        """Logic specifically for handling asynchronous requests."""
        # Admin path is already handled in __call__, no need to check here
        request.user = await self.get_user_async(request)
        return await self.get_response(request)
