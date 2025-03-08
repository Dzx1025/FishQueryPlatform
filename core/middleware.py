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
    """
    Middleware to extract JWT token from cookies for authentication

    This middleware allows token-based authentication using cookies instead of
    traditional Authorization headers, providing more flexibility for frontend
    integration.
    """

    def __init__(self, get_response):
        """
        Initialize the middleware

        Args:
            get_response: The next middleware or view in the chain
        """
        self.get_response = get_response
        super().__init__(get_response)

    def __call__(self, request):
        # If the request is for the admin site, skip this middleware
        if request.path.startswith("/admin/"):
            return self.get_response(request)

        return self.get_response(request)

    def process_request(self, request):
        """
        Process the request before it reaches the view

        Args:
            request: The HTTP request object
        """
        if not hasattr(request, 'user') or request.user.is_anonymous:
            request.user = SimpleLazyObject(lambda: get_user_jwt(request))

    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        This method is called just before Django calls the view.
        It's necessary for proper authentication with DRF.

        Args:
            request: The HTTP request object
            view_func: The view function
            view_args: Arguments to be passed to the view
            view_kwargs: Keyword arguments to be passed to the view
        """
        # Get JWT token from cookie
        token = request.COOKIES.get(settings.SIMPLE_JWT.get('AUTH_COOKIE'))

        if token:
            # If token exists in cookie, add it to the Authorization header
            # Some DRF authentication classes expect it there
            request.META['HTTP_AUTHORIZATION'] = f"Bearer {token}"

        return None
