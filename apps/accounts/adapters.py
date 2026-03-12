"""
Custom allauth adapters for better social account handling.
"""

import re

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model

User = get_user_model()


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom adapter to handle social account signup smoothly.
    """

    def pre_social_login(self, request, sociallogin):
        """
        Invoked just after a user successfully authenticates via a social provider,
        but before the login is actually processed.
        """
        # If user is already logged in, just connect the account
        if request.user.is_authenticated:
            return

        # Check if social account is already connected
        if sociallogin.is_existing:
            return

        # Try to connect to existing user with same email
        if sociallogin.email_addresses:
            email = sociallogin.email_addresses[0].email
            try:
                user = User.objects.get(email=email)
                sociallogin.connect(request, user)
            except User.DoesNotExist:
                pass

    def populate_user(self, request, sociallogin, data):
        """
        Populate user information from social provider data.
        """
        user = super().populate_user(request, sociallogin, data)

        # If username is not set or invalid, generate one from email or name
        if not user.username or user.username == "":
            # Try to get username from email
            if user.email:
                base_username = user.email.split("@")[0]
            # Or from first/last name
            elif user.first_name:
                base_username = user.first_name.lower()
            # Or from provider ID
            else:
                base_username = f"user_{sociallogin.account.uid[:8]}"

            # Clean username (only alphanumeric and underscores)
            base_username = re.sub(r"[^\w]", "_", base_username)

            # Make sure it's unique
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user.username = username

        return user

    def is_auto_signup_allowed(self, request, sociallogin):
        """
        Allow automatic signup if we have all required info.
        """
        # We can auto-signup if we have email and can generate username
        return True
