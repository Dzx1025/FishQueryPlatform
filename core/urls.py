from django.urls import path
from .views import (
    LoginAPIView,
    TokenRefreshView,
    RegisterAPIView,
    LogoutAPIView,
    UserProfileAPIView,
)

urlpatterns = [
    path("token/", LoginAPIView.as_view(), name="token_obtain_pair"),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('register/', RegisterAPIView.as_view(), name='register'),
    path('logout/', LogoutAPIView.as_view(), name='logout'),
    path('profile/', UserProfileAPIView.as_view(), name='profile'),
]
