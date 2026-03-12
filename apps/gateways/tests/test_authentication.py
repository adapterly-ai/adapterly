"""Tests for Gateway authentication classes."""

from django.test import TestCase

from rest_framework.exceptions import AuthenticationFailed

from apps.accounts.models import Account

from ..api.authentication import GatewaySecretAuthentication, RegistrationTokenAuthentication
from ..models import Gateway


class _MockRequest:
    """Minimal mock request with META dict."""

    def __init__(self, auth_header=""):
        self.META = {}
        if auth_header:
            self.META["HTTP_AUTHORIZATION"] = auth_header


class GatewaySecretAuthenticationTest(TestCase):
    def setUp(self):
        self.auth = GatewaySecretAuthentication()
        self.account = Account.objects.create(name="Test Account")
        self.secret, prefix, secret_hash = Gateway.generate_secret()
        self.gateway = Gateway.objects.create(
            account=self.account,
            gateway_id=Gateway.generate_gateway_id(),
            name="Test GW",
            secret_hash=secret_hash,
            secret_prefix=prefix,
            status="active",
        )

    def test_valid_secret_authenticates(self):
        request = _MockRequest(f"Bearer {self.secret}")
        result = self.auth.authenticate(request)
        self.assertIsNotNone(result)
        user, gateway = result
        self.assertIsNone(user)
        self.assertEqual(gateway.pk, self.gateway.pk)

    def test_invalid_secret_rejected(self):
        # Use correct prefix but wrong rest of secret
        fake_secret = self.secret[:10] + "x" * 30
        request = _MockRequest(f"Bearer {fake_secret}")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_unknown_prefix_rejected(self):
        request = _MockRequest("Bearer gs_ZZZZZZZZZZ_unknown")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_revoked_gateway_not_found(self):
        self.gateway.status = "revoked"
        self.gateway.save()
        request = _MockRequest(f"Bearer {self.secret}")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_inactive_gateway_not_found(self):
        self.gateway.status = "inactive"
        self.gateway.save()
        request = _MockRequest(f"Bearer {self.secret}")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_pending_gateway_accepted(self):
        self.gateway.status = "pending"
        self.gateway.save()
        request = _MockRequest(f"Bearer {self.secret}")
        result = self.auth.authenticate(request)
        self.assertIsNotNone(result)
        self.assertEqual(result[1].pk, self.gateway.pk)

    def test_non_bearer_gs_returns_none(self):
        request = _MockRequest("Bearer other_token")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_no_header_returns_none(self):
        request = _MockRequest("")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)


class RegistrationTokenAuthenticationTest(TestCase):
    def setUp(self):
        self.auth = RegistrationTokenAuthentication()
        self.account = Account.objects.create(name="Test Account")
        self.token = Gateway.generate_registration_token()
        secret, prefix, secret_hash = Gateway.generate_secret()
        self.gateway = Gateway.objects.create(
            account=self.account,
            gateway_id=Gateway.generate_gateway_id(),
            name="Pending GW",
            secret_hash=secret_hash,
            secret_prefix=prefix,
            status="pending",
            registration_token=self.token,
        )

    def test_valid_token_authenticates(self):
        request = _MockRequest(f"Bearer {self.token}")
        result = self.auth.authenticate(request)
        self.assertIsNotNone(result)
        user, gateway = result
        self.assertIsNone(user)
        self.assertEqual(gateway.pk, self.gateway.pk)

    def test_gs_prefix_skipped(self):
        request = _MockRequest("Bearer gs_some_secret_value")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_invalid_token_returns_none(self):
        request = _MockRequest("Bearer totally_unknown_token")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_non_pending_not_found(self):
        self.gateway.status = "active"
        self.gateway.save()
        request = _MockRequest(f"Bearer {self.token}")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)
