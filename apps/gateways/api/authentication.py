"""
Gateway authentication for the Sync API.

Gateways authenticate using their secret: Bearer gs_xxx...
Registration uses a one-time token.
"""

import hashlib
import logging

from rest_framework import authentication, exceptions

from ..models import Gateway

logger = logging.getLogger(__name__)


class GatewaySecretAuthentication(authentication.BaseAuthentication):
    """
    Authenticate gateway using its secret.

    Expected header: Authorization: Bearer gs_xxx...
    """

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer gs_"):
            return None

        secret = auth_header[7:]  # Remove "Bearer " prefix
        prefix = secret[:10]

        try:
            gateway = Gateway.objects.select_related("account").get(
                secret_prefix=prefix,
                status__in=["active", "pending"],
            )
        except Gateway.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid gateway secret")

        if not gateway.verify_secret(secret):
            raise exceptions.AuthenticationFailed("Invalid gateway secret")

        if gateway.status == "revoked":
            raise exceptions.AuthenticationFailed("Gateway has been revoked")

        # Return (user=None, auth=gateway) — gateway is not a user
        return (None, gateway)

    def authenticate_header(self, request):
        return "Bearer"


class RegistrationTokenAuthentication(authentication.BaseAuthentication):
    """
    Authenticate using a one-time registration token.

    Expected header: Authorization: Bearer <registration_token>
    """

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]

        # Skip if it looks like a gateway secret
        if token.startswith("gs_"):
            return None

        try:
            gateway = Gateway.objects.select_related("account").get(
                registration_token=token,
                status="pending",
            )
        except Gateway.DoesNotExist:
            return None  # Fall through to other authenticators

        # Return (user=None, auth=gateway)
        return (None, gateway)

    def authenticate_header(self, request):
        return "Bearer"
