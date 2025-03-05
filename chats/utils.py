from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse


def ratelimited_error(request, exception):
    """Custom response for rate-limited requests"""
    return JsonResponse({
        'error': 'Rate limit exceeded. Please try again later.'
    }, status=429)


def custom_exception_handler(exc, context):
    """Custom exception handler for DRF"""
    response = exception_handler(exc, context)

    if hasattr(exc, 'is_ratelimited') and exc.is_ratelimited:
        return Response(
            {'error': 'Rate limit exceeded. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    return response
