from core.serializers import HasuraTokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView


class HasuraTokenObtainPairView(TokenObtainPairView):
    serializer_class = HasuraTokenObtainPairSerializer
