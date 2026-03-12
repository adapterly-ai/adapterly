import random
import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

User = get_user_model()

# Characters for user_code — no ambiguous chars (0/O, 1/I/L)
USER_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
USER_CODE_LENGTH = 8


class Account(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    # External identification for MCP project mapping
    external_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
        db_index=True,
        help_text="External identifier for MCP project mapping",
    )

    # Default project for MCP operations
    default_project = models.ForeignKey(
        "mcp.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Default project for new tokens. Auto-set when first project is created.",
    )

    def __str__(self):
        return self.name


class AccountUser(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_admin = models.BooleanField(default=False)
    is_current_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("account", "user")

    def __str__(self):
        return f"{self.user.username} - {self.account.name}"

    def save(self, *args, **kwargs):
        """
        Ensure only one AccountUser is active per user.
        """
        if self.is_current_active:
            AccountUser.objects.filter(user=self.user, is_current_active=True).exclude(id=self.id).update(
                is_current_active=False
            )
        super().save(*args, **kwargs)


class UserInvitation(models.Model):
    """
    Model for inviting users to accounts.
    """

    email = models.EmailField()
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    invited_by = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    is_admin = models.BooleanField(default=False)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at_days = models.IntegerField(default=7)

    class Meta:
        unique_together = ("email", "account")

    def __str__(self):
        return f"Invitation {self.email} -> {self.account.name}"

    @property
    def expires_at(self):
        """Calculate expiration date based on created_at and expires_at_days."""
        from datetime import timedelta

        return self.created_at + timedelta(days=self.expires_at_days)

    def is_expired(self):
        """Check if invitation has expired."""
        return timezone.now() > self.expires_at

    def send_invitation_email(self, request):
        """
        Send invitation email to user.
        """
        from django.conf import settings
        from django.core.mail import EmailMultiAlternatives
        from django.template.loader import render_to_string

        # Build invitation URL
        invitation_url = request.build_absolute_uri(f"/account/invite/{self.token}/")

        inviter_name = self.invited_by.get_full_name() or self.invited_by.username

        # Email context
        context = {
            "invitation": self,
            "invitation_url": invitation_url,
            "inviter_name": inviter_name,
            "account_name": self.account.name,
            "expires_days": self.expires_at_days,
            "is_admin": self.is_admin,
            "app_name": getattr(settings, "APP_NAME", "Adapterly"),
            "app_tagline": getattr(settings, "APP_TAGLINE", "Integration platform for construction & logistics"),
            "app_primary_color": getattr(settings, "APP_PRIMARY_COLOR", "#667eea"),
            "app_secondary_color": getattr(settings, "APP_SECONDARY_COLOR", "#764ba2"),
        }

        app_name = getattr(settings, "APP_NAME", "Adapterly")

        # Subject
        subject = f"Invitation to join {self.account.name} on {app_name}"

        # Plain text version
        admin_line = "\nYou will have administrator privileges.\n" if self.is_admin else ""
        text_content = f"""Hi,

{inviter_name} has invited you to join {self.account.name} on {app_name}.
{admin_line}
Accept the invitation by visiting:
{invitation_url}

This invitation expires in {self.expires_at_days} days.

{app_name}""".strip()

        # HTML version
        html_content = render_to_string("accounts/emails/invitation.html", context)

        try:
            msg = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [self.email])
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)

            return True

        except Exception:
            # Log error but don't fail the invitation creation
            return False


def _generate_user_code():
    return "".join(random.choices(USER_CODE_CHARS, k=USER_CODE_LENGTH))


class DeviceAuthorization(models.Model):
    """
    Device authorization flow (RFC 8628-inspired).

    An external client (e.g. agent-view) creates a pending authorization,
    then displays a URL + user_code. The user opens the URL in a browser,
    logs in (e.g. via Google OAuth), and approves. The client polls for
    status and receives the DRF token once approved.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        EXPIRED = "expired", "Expired"

    device_code = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    user_code = models.CharField(max_length=8, default=_generate_user_code, unique=True, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    token = models.CharField(max_length=255, blank=True, default="")

    client_name = models.CharField(max_length=255, blank=True, default="Agent Terminal")
    client_ip = models.GenericIPAddressField(null=True, blank=True)

    expires_at = models.DateTimeField()
    poll_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"DeviceAuth {self.user_code} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            from datetime import timedelta

            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @staticmethod
    def cleanup_expired():
        """Mark expired pending authorizations."""
        DeviceAuthorization.objects.filter(
            status=DeviceAuthorization.Status.PENDING,
            expires_at__lt=timezone.now(),
        ).update(status=DeviceAuthorization.Status.EXPIRED)
