from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT token serializer with Hasura claims and user information
    """

    username_field = User.USERNAME_FIELD  # This will be 'email'

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add Hasura claims
        token["https://hasura.io/jwt/claims"] = {
            "x-hasura-allowed-roles": ["user", "admin"] if user.is_staff else ["user"],
            "x-hasura-default-role": "admin" if user.is_staff else "user",
            "x-hasura-user-id": str(user.id),
            "x-hasura-user-email": user.email,
            "x-hasura-is-staff": str(user.is_staff).lower(),
            "x-hasura-subscription": user.subscription_type,
        }

        # Add additional custom claims
        # token["email"] = user.email
        # token["username"] = user.username
        # token["is_staff"] = user.is_staff
        # token["subscription_type"] = user.subscription_type
        # token["daily_chat_quota"] = user.daily_chat_quota
        # token["chats_used_today"] = user.chats_used_today

        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        # Include user information in the response
        data.update(
            {
                "user_id": self.user.id,
                "email": self.user.email,
                "username": self.user.username,
                "is_staff": self.user.is_staff,
                "subscription_type": self.user.subscription_type,
            }
        )
        return data


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration with validation
    """

    email = serializers.EmailField(
        required=True,
        validators=[
            UniqueValidator(
                queryset=User.objects.all(),
                message="This email address is already registered.",
            )
        ],
    )
    username = serializers.CharField(required=True)
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        min_length=8,
        error_messages={"min_length": "Password must be at least 8 characters long."},
    )

    class Meta:
        model = User
        fields = ("email", "username", "password")
        extra_kwargs = {"password": {"write_only": True}}

    def validate_password(self, value):
        """
        Validate password strength
        """
        if value.isdigit():
            raise serializers.ValidationError("Password cannot be entirely numeric.")
        if len(value) < 8:
            raise serializers.ValidationError(
                "Password must be at least 8 characters long."
            )
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data["email"],
            username=validated_data["username"],
            password=validated_data["password"],
            is_staff=False,
            is_superuser=False,
        )
        return user

    def to_representation(self, instance):
        """
        Override to exclude password from response
        """
        data = super().to_representation(instance)
        return {"email": instance.email, "username": instance.username}


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for user profile information and updates
    """

    is_subscription_active = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "subscription_type",
            "is_subscription_active",
            "daily_message_quota",
            "messages_used_today",
            "subscription_expiry",
        )
        read_only_fields = (
            "id",
            "email",
            "subscription_type",
            "is_subscription_active",
            "daily_message_quota",
            "messages_used_today",
            "subscription_expiry",
        )

    def validate(self, attrs):
        """Ensure only username is being updated"""
        if self.instance and self.partial:
            allowed_fields = {"username"}
            provided_fields = set(self.initial_data.keys())
            invalid_fields = provided_fields - allowed_fields
            if invalid_fields:
                raise serializers.ValidationError(
                    f"Updating invalid fields: {', '.join(invalid_fields)}"
                )

        return attrs

    def get_is_subscription_active(self, obj):
        """
        Return the active status of the subscription
        """
        return obj.is_subscription_active()
