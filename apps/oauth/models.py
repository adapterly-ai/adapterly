import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.accounts.models import Account


class OAuthApplication(models.Model):
    """
    OAuth2 client application (e.g. ChatGPT).
    """

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="oauth_applications",
        help_text="Account whose API keys will be created on token exchange.",
    )
    name = models.CharField(max_length=200)
    client_id = models.CharField(max_length=50, unique=True, db_index=True)
    client_secret_hash = models.CharField(max_length=128)
    client_secret_prefix = models.CharField(max_length=10)
    redirect_uri = models.URLField(max_length=500)

    # Agent profile — if set, tokens inherit this profile (overrides mode)
    profile = models.ForeignKey(
        "mcp.AgentProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="oauth_applications",
        help_text="Agent profile for tokens. If set, overrides mode.",
    )

    # Project binding — tokens can be scoped to a project
    project = models.ForeignKey(
        "mcp.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="oauth_applications",
        help_text="Project to bind tokens to. If empty, uses account default.",
    )

    mode = models.CharField(
        max_length=20,
        choices=[("safe", "Safe Mode"), ("power", "Power Mode")],
        default="safe",
        help_text="Default mode for API keys (used only if no profile is set).",
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "OAuth Application"

    def __str__(self):
        return f"{self.name} ({self.client_id})"

    @classmethod
    def generate_credentials(cls):
        """Generate client_id, client_secret, prefix, and hash."""
        client_id = f"oa_{secrets.token_urlsafe(16)}"
        client_secret = f"os_{secrets.token_urlsafe(32)}"
        prefix = client_secret[:10]
        secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()
        return client_id, client_secret, prefix, secret_hash

    def verify_secret(self, secret: str) -> bool:
        return hashlib.sha256(secret.encode()).hexdigest() == self.client_secret_hash


class AuthorizationCode(models.Model):
    """
    Single-use authorization code with 10-minute TTL.
    """

    application = models.ForeignKey(OAuthApplication, on_delete=models.CASCADE, related_name="auth_codes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)

    code = models.CharField(max_length=128, unique=True, db_index=True)
    redirect_uri = models.URLField(max_length=500)
    state = models.CharField(max_length=500, blank=True)

    # PKCE (RFC 7636)
    code_challenge = models.CharField(max_length=128, blank=True)
    code_challenge_method = models.CharField(max_length=10, blank=True)

    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Authorization Code"

    def __str__(self):
        return f"Code for {self.application.name} ({self.user})"

    @classmethod
    def generate_code(cls):
        return secrets.token_urlsafe(48)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired
