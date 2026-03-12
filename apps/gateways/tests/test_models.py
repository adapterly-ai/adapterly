"""Tests for Gateway and GatewayAuditLog models."""

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Account

from ..models import Gateway, GatewayAuditLog


class GatewayModelTest(TestCase):
    def setUp(self):
        self.account = Account.objects.create(name="Test Account")
        secret, prefix, secret_hash = Gateway.generate_secret()
        self.secret = secret
        self.gateway = Gateway.objects.create(
            account=self.account,
            gateway_id=Gateway.generate_gateway_id(),
            name="Test Gateway",
            secret_hash=secret_hash,
            secret_prefix=prefix,
            status="active",
        )

    def test_generate_gateway_id_format(self):
        gw_id = Gateway.generate_gateway_id()
        self.assertTrue(gw_id.startswith("gw_"))
        self.assertGreaterEqual(len(gw_id), 22)

    def test_generate_gateway_id_unique(self):
        id1 = Gateway.generate_gateway_id()
        id2 = Gateway.generate_gateway_id()
        self.assertNotEqual(id1, id2)

    def test_generate_secret_format(self):
        secret, prefix, secret_hash = Gateway.generate_secret()
        self.assertTrue(secret.startswith("gs_"))
        self.assertEqual(prefix, secret[:10])
        self.assertEqual(len(secret_hash), 64)

    def test_verify_secret_valid(self):
        self.assertTrue(self.gateway.verify_secret(self.secret))

    def test_verify_secret_invalid(self):
        self.assertFalse(self.gateway.verify_secret("wrong_secret"))

    def test_generate_registration_token(self):
        token = Gateway.generate_registration_token()
        self.assertTrue(len(token) > 0)
        # Should be url-safe
        for char in token:
            self.assertIn(char, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")

    def test_mark_seen_updates_timestamp(self):
        self.assertIsNone(self.gateway.last_seen_at)
        self.gateway.mark_seen()
        self.gateway.refresh_from_db()
        self.assertIsNotNone(self.gateway.last_seen_at)

    def test_str_representation(self):
        expected = f"Test Gateway ({self.gateway.gateway_id})"
        self.assertEqual(str(self.gateway), expected)


class GatewayAuditLogModelTest(TestCase):
    def setUp(self):
        self.account = Account.objects.create(name="Test Account")
        secret, prefix, secret_hash = Gateway.generate_secret()
        self.gateway = Gateway.objects.create(
            account=self.account,
            gateway_id=Gateway.generate_gateway_id(),
            name="Test Gateway",
            secret_hash=secret_hash,
            secret_prefix=prefix,
            status="active",
        )

    def test_audit_log_create(self):
        now = timezone.now()
        log = GatewayAuditLog.objects.create(
            gateway=self.gateway,
            account=self.account,
            tool_name="testsys_users_list",
            tool_type="system_read",
            duration_ms=150,
            success=True,
            session_id="sess-123",
            mode="safe",
            gateway_timestamp=now,
        )
        log.refresh_from_db()
        self.assertEqual(log.tool_name, "testsys_users_list")
        self.assertEqual(log.tool_type, "system_read")
        self.assertEqual(log.duration_ms, 150)
        self.assertTrue(log.success)

    def test_audit_log_str(self):
        log = GatewayAuditLog.objects.create(
            gateway=self.gateway,
            account=self.account,
            tool_name="testsys_users_list",
            tool_type="system_read",
            success=True,
            gateway_timestamp=timezone.now(),
        )
        self.assertIn(self.gateway.gateway_id, str(log))
        self.assertIn("testsys_users_list", str(log))
        self.assertIn("OK", str(log))

        log_fail = GatewayAuditLog.objects.create(
            gateway=self.gateway,
            account=self.account,
            tool_name="testsys_users_create",
            tool_type="system_write",
            success=False,
            error_message="Permission denied",
            gateway_timestamp=timezone.now(),
        )
        self.assertIn("FAIL", str(log_fail))
