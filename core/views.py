from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings

from .responses import APIResponse
from .serializers import (
    CustomTokenObtainPairSerializer,
    UserRegistrationSerializer,
    UserProfileSerializer
)


def set_jwt_cookies(response, access_token, refresh_token=None):
    """
    Set JWT cookies in the response
    """
    cookie_settings = {
        'httponly': settings.SIMPLE_JWT.get('AUTH_COOKIE_HTTP_ONLY', True),
        'secure': settings.SIMPLE_JWT.get('AUTH_COOKIE_SECURE', True),
        'domain': settings.SIMPLE_JWT.get('AUTH_COOKIE_DOMAIN'),
        'path': settings.SIMPLE_JWT.get('AUTH_COOKIE_PATH', '/'),
        'samesite': settings.SIMPLE_JWT.get('AUTH_COOKIE_SAMESITE', 'Lax'),
    }

    access_cookie_name = settings.SIMPLE_JWT.get('AUTH_COOKIE', 'access_token')
    response.set_cookie(
        access_cookie_name,
        access_token,
        max_age=settings.SIMPLE_JWT.get('ACCESS_TOKEN_LIFETIME').total_seconds(),
        **cookie_settings
    )

    if refresh_token:
        refresh_cookie_name = settings.SIMPLE_JWT.get('AUTH_COOKIE_REFRESH', 'refresh_token')
        response.set_cookie(
            refresh_cookie_name,
            refresh_token,
            max_age=settings.SIMPLE_JWT.get('REFRESH_TOKEN_LIFETIME').total_seconds(),
            **cookie_settings
        )

    return response


class LoginAPIView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)

            if response.status_code == status.HTTP_200_OK:
                access_token = response.data.get('access')
                refresh_token = response.data.get('refresh')
                userid = response.data.get('user_id')
                email = response.data.get('email')

                response = APIResponse.success(
                    data={'userid': userid, 'email': email},
                    message="Login successful"
                )
                return set_jwt_cookies(response, access_token, refresh_token)
        except Exception as e:
            return APIResponse.error(
                message=e.args[0],
                code=status.HTTP_401_UNAUTHORIZED
            )


class RegisterAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)

            response = APIResponse.success(
                data={'email': user.email},
                message="Registration successful",
                code=status.HTTP_201_CREATED
            )

            access_token = str(refresh.access_token)
            refresh_token = str(refresh)
            return set_jwt_cookies(response, access_token, refresh_token)

        return APIResponse.error(
            errors=serializer.errors,
            message="Validation error"
        )


class LogoutAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            refresh_token = request.COOKIES.get(settings.SIMPLE_JWT.get('AUTH_COOKIE_REFRESH'))
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()

            response = APIResponse.success(message="Logout successful")

            response.delete_cookie(
                settings.SIMPLE_JWT.get('AUTH_COOKIE'),
                domain=settings.SIMPLE_JWT.get('AUTH_COOKIE_DOMAIN'),
                path=settings.SIMPLE_JWT.get('AUTH_COOKIE_PATH', '/'),
            )
            response.delete_cookie(
                settings.SIMPLE_JWT.get('AUTH_COOKIE_REFRESH'),
                domain=settings.SIMPLE_JWT.get('AUTH_COOKIE_DOMAIN'),
                path=settings.SIMPLE_JWT.get('AUTH_COOKIE_PATH', '/'),
            )

            return response

        except Exception as e:
            return APIResponse.error(
                errors=str(e),
                message="Logout failed"
            )


class TokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.SIMPLE_JWT.get('AUTH_COOKIE_REFRESH'))

        if not refresh_token:
            return APIResponse.error(message="Refresh token not found")

        try:
            refresh = RefreshToken(refresh_token)
            access_token = str(refresh.access_token)

            if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', False):
                refresh_token = str(refresh)

            response = APIResponse.success(message="Token refreshed successfully")

            return set_jwt_cookies(
                response,
                access_token,
                refresh_token if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', False) else None
            )

        except Exception as e:
            return APIResponse.error(
                errors=str(e),
                message="Token refresh failed",
                code=status.HTTP_401_UNAUTHORIZED
            )


class UserProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        request.user.reset_daily_quota()

        serializer = UserProfileSerializer(request.user)
        return APIResponse.success(data=serializer.data)

    def patch(self, request):
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return APIResponse.success(
                data=serializer.data,
                message="Profile updated successfully"
            )

        return APIResponse.error(
            errors=serializer.errors,
            message="Validation error"
        )
