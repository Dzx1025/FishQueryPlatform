from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView


class HasuraTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add Hasura claims
        token["https://hasura.io/jwt/claims"] = {
            # Mandatory fields
            "x-hasura-allowed-roles": ["user", "admin"] if user.is_staff else ["user"],
            "x-hasura-default-role": "admin" if user.is_staff else "user",
            "x-hasura-user-id": str(user.id),  # Must be string
            # Optional custom fields
            "x-hasura-user-email": user.email,
            "x-hasura-is-staff": str(user.is_staff).lower(),  # "true" or "false"
        }

        # You can add additional custom claims
        token["email"] = user.email
        token["username"] = user.username
        token["is_staff"] = user.is_staff

        return token
