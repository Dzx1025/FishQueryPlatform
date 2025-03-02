from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from django.utils import timezone
from datetime import date

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
        response = super().post(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            access_token = response.data.get('access')
            refresh_token = response.data.get('refresh')

            user_id = response.data.get('user_id')
            email = response.data.get('email')

            response = set_jwt_cookies(response, access_token, refresh_token)

            response.data = {
                'status': 'success',
                'message': 'Login successful',
                'data': {
                    'user_id': user_id,
                    'email': email
                }
            }

        return response


class RegisterAPIView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)

            response = Response({
                'status': 'success',
                'message': 'Registration successful',
                'data': {
                    'user_id': user.id,
                    'email': user.email
                }
            }, status=status.HTTP_201_CREATED)

            access_token = str(refresh.access_token)
            refresh_token = str(refresh)
            response = set_jwt_cookies(response, access_token, refresh_token)

            return response

        return Response({
            'status': 'error',
            'message': 'Validation error',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.COOKIES.get(settings.SIMPLE_JWT.get('AUTH_COOKIE_REFRESH'))
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()

            response = Response({
                'status': 'success',
                'message': 'Logout successful'
            }, status=status.HTTP_200_OK)

            response.delete_cookie(settings.SIMPLE_JWT.get('AUTH_COOKIE'))
            response.delete_cookie(settings.SIMPLE_JWT.get('AUTH_COOKIE_REFRESH'))

            return response

        except Exception as e:
            return Response({
                'status': 'error',
                'message': 'Logout failed',
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class TokenRefreshView(APIView):
    permission_classes = []

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.SIMPLE_JWT.get('AUTH_COOKIE_REFRESH'))

        if not refresh_token:
            return Response({
                'status': 'error',
                'message': 'Refresh token not found'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            refresh = RefreshToken(refresh_token)
            access_token = str(refresh.access_token)

            if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', False):
                refresh_token = str(refresh)

            response = Response({
                'status': 'success',
                'message': 'Token refreshed successfully'
            })

            response = set_jwt_cookies(
                response,
                access_token,
                refresh_token if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', False) else None
            )

            return response

        except Exception as e:
            return Response({
                'status': 'error',
                'message': 'Token refresh failed',
                'error': str(e)
            }, status=status.HTTP_401_UNAUTHORIZED)


class UserProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        request.user.reset_daily_chat_counter()

        serializer = UserProfileSerializer(request.user)
        return Response({
            'status': 'success',
            'data': serializer.data
        })

    def patch(self, request):
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'message': 'Profile updated successfully',
                'data': serializer.data
            })

        return Response({
            'status': 'error',
            'message': 'Validation error',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
