from django.utils.functional import SimpleLazyObject
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.deprecation import MiddlewareMixin

User = get_user_model()


def get_user_jwt(request):
    """
    Extract JWT token from cookies and retrieve the user

    Args:
        request: The HTTP request object containing cookies

    Returns:
        User object if token is valid, None otherwise
    """
    # Get token from cookies
    token = request.COOKIES.get(settings.SIMPLE_JWT.get('AUTH_COOKIE'))

    if token:
        # Validate token using JWTAuthentication
        auth = JWTAuthentication()
        try:
            # Don't add 'Bearer' prefix - the token in the cookie is the raw token
            validated_token = auth.get_validated_token(token)
            user = auth.get_user(validated_token)
            return user
        except Exception as e:
            print(f"JWT Authentication error: {str(e)}")
            return None

    return None


class JWTCookieMiddleware(MiddlewareMixin):
    def __init__(self, get_response):
        self.get_response = get_response
        super().__init__(get_response)

    def __call__(self, request):
        # Skip JWT authentication for admin URLs
        if request.path.startswith("/admin/"):
            return self.get_response(request)

        # Token authentication
        self.process_request(request)

        # Get view function information (simulate process_view call)
        response = self.get_response(request)

        return response

    def process_request(self, request):
        if not hasattr(request, 'user') or request.user.is_anonymous:
            request.user = SimpleLazyObject(lambda: get_user_jwt(request))

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Get JWT token from cookie
        token = request.COOKIES.get(settings.SIMPLE_JWT.get('AUTH_COOKIE'))

        if token:
            # If token exists in cookie, add it to the Authorization header
            request.META['HTTP_AUTHORIZATION'] = f"Bearer {token}"

        return None
