"""
Signals for automatic account creation.
"""

from allauth.account.signals import user_signed_up
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import Account, AccountUser

User = get_user_model()


@receiver(user_signed_up)
@transaction.atomic
def create_personal_account_on_signup(sender, request, user, **kwargs):
    """
    Automatically create a personal account when a user signs up
    (via regular signup or social login).
    """
    # Check if user already has an account
    if AccountUser.objects.filter(user=user).exists():
        return

    # Create personal account
    account_name = f"{user.username}'s Account"
    if user.first_name:
        account_name = f"{user.first_name}'s Account"

    account = Account.objects.create(name=account_name)

    # Link user to account as admin
    AccountUser.objects.create(account=account, user=user, is_admin=True, is_current_active=True)


@receiver(post_save, sender=User)
@transaction.atomic
def ensure_user_has_account(sender, instance, created, **kwargs):
    """
    Fallback: Ensure every user has at least one account.
    This catches cases where signals might not fire.
    """
    if created:
        # Give a small delay to let other signals fire first
        # Check if user has an account
        if not AccountUser.objects.filter(user=instance).exists():
            account = Account.objects.create(name=f"{instance.username}'s Account")
            AccountUser.objects.create(account=account, user=instance, is_admin=True, is_current_active=True)
