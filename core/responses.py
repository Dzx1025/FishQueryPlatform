from rest_framework.response import Response


class APIResponse:
    @staticmethod
    def success(data=None, message="Operation successful", code=200):
        return Response({
            "status": "success",
            "code": code,
            "message": message,
            "data": data,
            "errors": None
        }, status=code)

    @staticmethod
    def error(errors=None, message="Operation failed", code=400):
        return Response({
            "status": "error",
            "code": code,
            "message": message,
            "data": None,
            "errors": errors
        }, status=code)
