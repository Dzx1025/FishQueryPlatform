from rest_framework.views import exception_handler
from rest_framework import status
from core.responses import APIResponse


def ratelimited_error(request, exception):
    """Custom response for rate-limited requests"""
    return APIResponse.error(
        message='Rate limit exceeded. Please try again later.',
        code=status.HTTP_429_TOO_MANY_REQUESTS
    )


def custom_exception_handler(exc, context):
    """Custom exception handler that formats all errors using APIResponse"""
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)

    if response is not None:
        # Get the error details
        error_message = str(exc)
        status_code = response.status_code

        # For validation errors, get the detailed error dict
        errors = response.data if hasattr(response, 'data') else None

        # Return formatted response
        return APIResponse.error(
            errors=errors,
            message=error_message,
            code=status_code
        )

    # Handle rate limiting specifically
    if hasattr(exc, 'is_ratelimited') and exc.is_ratelimited:
        return APIResponse.error(
            message="Rate limit exceeded. Please try again later.",
            code=status.HTTP_429_TOO_MANY_REQUESTS
        )

    # For unhandled exceptions
    return APIResponse.error(
        message="An unexpected error occurred",
        code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )
