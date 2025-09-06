from asgiref.sync import sync_to_async
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class CustomUserManager(BaseUserManager):
    """
    Custom user manager where email is the unique identifier
    for authentication instead of username.
    """

    def create_user(self, email, username, password=None, **extra_fields):
        """
        Create and save a user with the given email, username and password.
        """
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        """
        Create and save a SuperUser with the given email, username and password.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, username, password, **extra_fields)


class CustomUser(AbstractUser):
    """
    Custom User Model that uses email as the unique identifier
    instead of username and allows for non-unique usernames.
    """

    email = models.EmailField(
        unique=True,
        verbose_name="Email Address",
        error_messages={
            "unique": "A user with that email already exists.",
        },
    )
    username = models.CharField(
        max_length=150,
        verbose_name="Username",
        help_text="Username is not used for login and does not need to be unique.",
    )

    # Override the groups and user_permissions fields with custom related_name
    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name="groups",
        blank=True,
        help_text="The groups this user belongs to.",
        related_name="custom_user_set",
        related_query_name="custom_user",
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        verbose_name="user permissions",
        blank=True,
        help_text="Specific permissions for this user.",
        related_name="custom_user_set",
        related_query_name="custom_user",
    )

    # Chat quota management
    daily_message_quota = models.IntegerField(
        default=10,
        verbose_name="Daily Chat Quota",
        help_text="Maximum number of chats allowed per day",
    )
    messages_used_today = models.IntegerField(
        default=0,
        verbose_name="Chats Used Today",
        help_text="Number of chats used today",
    )
    last_message_reset = models.DateField(
        default=timezone.now,
        verbose_name="Last Chat Counter Reset",
        help_text="Date when the chat counter was last reset",
    )

    # Subscription management
    SUBSCRIPTION_CHOICES = [
        ("free", "Free"),
        ("basic", "Basic"),
        ("premium", "Premium"),
        ("enterprise", "Enterprise"),
    ]
    subscription_type = models.CharField(
        max_length=20,
        choices=SUBSCRIPTION_CHOICES,
        default="free",
        verbose_name="Subscription Type",
    )
    subscription_expiry = models.DateTimeField(
        null=True, blank=True, verbose_name="Subscription Expiry Date"
    )

    # Email is used for login, not username
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]  # Required when running createsuperuser

    objects = CustomUserManager()

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        unique_together = []  # No unique constraints on multiple fields

    def __str__(self):
        return self.email

    def reset_daily_quota(self):
        """Reset the daily chat counter if it's a new day"""
        today = timezone.now().date()
        if self.last_message_reset != today:
            self.messages_used_today = 0
            self.last_message_reset = today
            self.save(update_fields=["messages_used_today", "last_message_reset"])

    def can_send_message(self):
        """Check if the user can chat based on their quota"""
        self.reset_daily_quota()
        return self.messages_used_today < self.daily_message_quota

    def increment_message_count(self):
        """Use one chat from the quota if available"""
        if self.can_send_message():
            self.messages_used_today += 1
            self.save(update_fields=["messages_used_today"])
            return True
        return False

    def is_subscription_active(self):
        """Check if the user's subscription is active"""
        if self.subscription_type == "free":
            return True
        if not self.subscription_expiry:
            return False
        return timezone.now() < self.subscription_expiry
