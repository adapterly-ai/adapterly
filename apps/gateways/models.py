"""
Gateway models — control plane side.

Tracks registered gateways, their health, and sync state.
Credentials never pass through the control plane.
"""

import hashlib
import secrets

from django.db import models
from django.utils import timezone

from apps.accounts.models import Account


class Gateway(models.Model):
    """
    Registered gateway instance.

    Each gateway has a unique gateway_id and authenticates to the
    control plane using a hashed secret (Bearer token).
    """

    STATUS_CHOICES = [
        ("pending", "Pending Registration"),
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("revoked", "Revoked"),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="gateways")
    gateway_id = models.CharField(
        max_length=50, unique=True, db_index=True,
        help_text="Public gateway identifier (e.g., gw_abc123)",
    )
    name = models.CharField(max_length=200, help_text="Human-readable name")
    description = models.TextField(blank=True)

    # Authentication — hashed secret, never stored in plaintext
    secret_hash = models.CharField(max_length=128, help_text="SHA-256 hash of the gateway secret")
    secret_prefix = models.CharField(max_length=10, help_text="First 10 chars for lookup")

    # Status and health
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_spec_sync_at = models.DateTimeField(null=True, blank=True)
    last_key_sync_at = models.DateTimeField(null=True, blank=True)
    last_audit_push_at = models.DateTimeField(null=True, blank=True)

    # Gateway metadata (reported via health endpoint)
    version = models.CharField(max_length=50, blank=True)
    active_sessions = models.IntegerField(default=0)
    hostname = models.CharField(max_length=255, blank=True)

    # Credential status — control plane knows WHICH systems have credentials, not the values
    credential_status = models.JSONField(
        default=dict, blank=True,
        help_text='{"system_alias": true/false} — whether gateway has credentials for each system',
    )

    # Registration token (one-time, used during initial registration)
    registration_token = models.CharField(
        max_length=64, unique=True, null=True, blank=True,
        help_text="One-time token for gateway registration (cleared after use)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"{self.name} ({self.gateway_id})"

    @classmethod
    def generate_gateway_id(cls) -> str:
        """Generate a unique gateway ID."""
        return f"gw_{secrets.token_urlsafe(16)}"

    @classmethod
    def generate_secret(cls) -> tuple[str, str, str]:
        """
        Generate a gateway secret.

        Returns:
            (full_secret, prefix, sha256_hash)
        """
        secret = f"gs_{secrets.token_urlsafe(32)}"
        prefix = secret[:10]
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        return secret, prefix, secret_hash

    @classmethod
    def generate_registration_token(cls) -> str:
        """Generate a one-time registration token."""
        return secrets.token_urlsafe(48)

    def verify_secret(self, secret: str) -> bool:
        """Verify a gateway secret against the stored hash."""
        return hashlib.sha256(secret.encode()).hexdigest() == self.secret_hash

    def mark_seen(self):
        """Update last_seen_at timestamp."""
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at"])


class GatewayAuditLog(models.Model):
    """
    Audit log entries received from gateways.

    These are sanitized — no credentials or sensitive data.
    Pushed by gateways in batches.
    """

    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE, related_name="audit_logs")
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="gateway_audit_logs")

    tool_name = models.CharField(max_length=255, db_index=True)
    tool_type = models.CharField(max_length=50)
    duration_ms = models.IntegerField(default=0)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    error_category = models.CharField(max_length=30, blank=True)
    session_id = models.CharField(max_length=100, blank=True)
    mode = models.CharField(max_length=20, default="safe")

    # Timestamps
    gateway_timestamp = models.DateTimeField(help_text="When the event occurred on the gateway")
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-gateway_timestamp"]
        indexes = [
            models.Index(fields=["account", "gateway_timestamp"]),
            models.Index(fields=["gateway", "gateway_timestamp"]),
        ]

    def __str__(self):
        status = "OK" if self.success else "FAIL"
        return f"[{self.gateway.gateway_id}] {self.tool_name} [{status}]"
