from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _
from .models import CustomUser
from django import forms


class CustomUserAdminForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = '__all__'

    def clean_username(self):
        # Override the default unique username validation
        return self.cleaned_data['username']


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('email', 'username')

    def clean_username(self):
        # Override the default unique username validation for new users
        return self.cleaned_data['username']


class CustomUserAdmin(UserAdmin):
    form = CustomUserAdminForm
    add_form = CustomUserCreationForm  # Add this line

    # Rest of your class remains the same
    model = CustomUser
    list_display = ('email', 'username', 'is_staff', 'subscription_type', 'daily_message_quota')
    list_filter = ('is_staff', 'is_superuser', 'subscription_type')
    search_fields = ('email', 'username')
    ordering = ('email',)

    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        (_('Personal info'), {'fields': ()}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
        (_('Chat Management'), {'fields': ('daily_message_quota', 'messages_used_today', 'last_message_reset')}),
        (_('Subscription'), {'fields': ('subscription_type', 'subscription_expiry')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2', 'is_staff', 'is_superuser'),
        }),
        (_('Chat Management'), {'fields': ('daily_chat_quota',)}),
        (_('Subscription'), {'fields': ('subscription_type', 'subscription_expiry')}),
    )


admin.site.register(CustomUser, CustomUserAdmin)
