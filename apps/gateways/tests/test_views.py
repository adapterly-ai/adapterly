"""Tests for Gateway Sync API views."""

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from apps.accounts.models import Account
from apps.mcp.models import MCPApiKey, Project, ProjectIntegration
from apps.systems.models import System, Interface, Resource, Action

from ..models import Gateway, GatewayAuditLog


class GatewaySyncTestCase(TestCase):
    """Base test case with common gateway setup."""

    def setUp(self):
        self.client = APIClient()
        self.account = Account.objects.create(name="Test Account")

        # Active gateway with real secret
        self.secret, prefix, secret_hash = Gateway.generate_secret()
        self.gateway = Gateway.objects.create(
            account=self.account,
            gateway_id=Gateway.generate_gateway_id(),
            name="Active Gateway",
            secret_hash=secret_hash,
            secret_prefix=prefix,
            status="active",
        )

        # Pending gateway with registration token
        self.reg_token = Gateway.generate_registration_token()
        dummy_secret, dummy_prefix, dummy_hash = Gateway.generate_secret()
        self.pending_gateway = Gateway.objects.create(
            account=self.account,
            gateway_id=Gateway.generate_gateway_id(),
            name="Pending Gateway",
            secret_hash=dummy_hash,
            secret_prefix=dummy_prefix,
            status="pending",
            registration_token=self.reg_token,
        )

    def auth(self, secret=None):
        """Set Authorization header."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {secret or self.secret}")

    def auth_token(self, token=None):
        """Set Authorization header with registration token."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token or self.reg_token}")


class TestRegisterEndpoint(GatewaySyncTestCase):
    URL = "/gateway-sync/v1/register"

    def test_register_success(self):
        self.auth_token()
        response = self.client.post(self.URL, {}, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("gateway_id", data)
        self.assertIn("gateway_secret", data)
        self.assertTrue(data["gateway_secret"].startswith("gs_"))

    def test_register_sets_active_status(self):
        self.auth_token()
        self.client.post(self.URL, {}, format="json")
        self.pending_gateway.refresh_from_db()
        self.assertEqual(self.pending_gateway.status, "active")

    def test_register_clears_token(self):
        self.auth_token()
        self.client.post(self.URL, {}, format="json")
        self.pending_gateway.refresh_from_db()
        self.assertIsNone(self.pending_gateway.registration_token)

    def test_register_with_name(self):
        self.auth_token()
        response = self.client.post(self.URL, {"name": "My Custom GW"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.pending_gateway.refresh_from_db()
        self.assertEqual(self.pending_gateway.name, "My Custom GW")

    def test_register_invalid_token_401(self):
        self.auth_token("totally_wrong_token")
        response = self.client.post(self.URL, {}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_register_already_used_token_401(self):
        # First registration succeeds
        self.auth_token()
        self.client.post(self.URL, {}, format="json")
        # Second attempt fails (token cleared)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.reg_token}")
        response = self.client.post(self.URL, {}, format="json")
        self.assertEqual(response.status_code, 401)


class TestSyncSpecsEndpoint(GatewaySyncTestCase):
    URL = "/gateway-sync/v1/specs"

    def setUp(self):
        super().setUp()
        self.system = System.objects.create(
            name="Test System",
            alias="testsys",
            display_name="Test System",
            description="A test system",
            system_type="other",
            is_active=True,
        )
        self.interface = Interface.objects.create(
            system=self.system,
            alias="testapi",
            name="Test API",
            type="API",
            base_url="https://api.example.com",
            auth={"type": "bearer"},
        )
        self.resource = Resource.objects.create(
            interface=self.interface,
            alias="users",
            name="Users",
            description="User management",
        )
        self.action = Action.objects.create(
            resource=self.resource,
            alias="list",
            name="List Users",
            description="List all users",
            method="GET",
            path="/api/v1/users",
            is_mcp_enabled=True,
        )

    def test_sync_specs_returns_systems(self):
        self.auth()
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("systems", data)
        # Seed data from migrations is included — check our system is present
        aliases = [s["alias"] for s in data["systems"]]
        self.assertIn("testsys", aliases)
        system = next(s for s in data["systems"] if s["alias"] == "testsys")
        self.assertEqual(len(system["interfaces"]), 1)
        self.assertEqual(len(system["resources"]), 1)
        self.assertEqual(len(system["actions"]), 1)

    def test_sync_specs_since_filter(self):
        self.auth()
        # Use a far-future timestamp — nothing updated after this
        response = self.client.get(f"{self.URL}?since=2099-01-01T00:00:00Z")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["systems"]), 0)

    def test_sync_specs_deleted_ids(self):
        self.auth()
        # Mark system inactive (auto_now on updated_at ensures it's fresh)
        self.system.is_active = False
        self.system.save()
        response = self.client.get(f"{self.URL}?since=2000-01-01T00:00:00Z")
        data = response.json()
        self.assertIn(self.system.id, data["deleted_ids"])

    def test_sync_specs_updates_timestamps(self):
        self.auth()
        self.assertIsNone(self.gateway.last_spec_sync_at)
        self.client.get(self.URL)
        self.gateway.refresh_from_db()
        self.assertIsNotNone(self.gateway.last_spec_sync_at)
        self.assertIsNotNone(self.gateway.last_seen_at)

    def test_sync_specs_no_auth_401(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 401)

    def test_sync_specs_invalid_secret_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer gs_INVALIDPREFIX_wrong")
        response = self.client.get(self.URL)
        self.assertIn(response.status_code, (401, 403))


class TestSyncKeysEndpoint(GatewaySyncTestCase):
    URL = "/gateway-sync/v1/keys"

    def setUp(self):
        super().setUp()
        self.system = System.objects.create(
            name="Test System",
            alias="testsys",
            display_name="Test System",
            system_type="other",
            is_active=True,
        )
        self.project = Project.objects.create(
            account=self.account,
            name="Test Project",
            slug="test-project",
            description="A test project",
        )
        self.integration = ProjectIntegration.objects.create(
            project=self.project,
            system=self.system,
            credential_source="account",
            external_id="ext-123",
            is_enabled=True,
        )
        key, prefix, key_hash = MCPApiKey.generate_key()
        self.api_key = MCPApiKey.objects.create(
            account=self.account,
            name="Test Key",
            key_prefix=prefix,
            key_hash=key_hash,
            project=self.project,
            is_admin=False,
            mode="safe",
            is_active=True,
        )

    def test_sync_keys_returns_data(self):
        self.auth()
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("keys", data)
        self.assertIn("projects", data)
        self.assertIn("integrations", data)
        self.assertGreaterEqual(len(data["keys"]), 1)
        self.assertEqual(len(data["projects"]), 1)
        self.assertEqual(len(data["integrations"]), 1)

    def test_sync_keys_scoped_to_account(self):
        other_account = Account.objects.create(name="Other Account")
        other_project = Project.objects.create(
            account=other_account,
            name="Other Project",
            slug="other-project",
        )
        key, prefix, key_hash = MCPApiKey.generate_key()
        MCPApiKey.objects.create(
            account=other_account,
            name="Other Key",
            key_prefix=prefix,
            key_hash=key_hash,
            project=other_project,
            is_active=True,
        )
        self.auth()
        response = self.client.get(self.URL)
        data = response.json()
        # Should only return our account's data
        for k in data["keys"]:
            self.assertEqual(k["account_id"], self.account.id)
        for p in data["projects"]:
            self.assertEqual(p["account_id"], self.account.id)

    def test_sync_keys_since_filter(self):
        self.auth()
        response = self.client.get(f"{self.URL}?since=2099-01-01T00:00:00Z")
        data = response.json()
        self.assertEqual(len(data["keys"]), 0)
        self.assertEqual(len(data["projects"]), 0)

    def test_sync_keys_excludes_inactive(self):
        self.api_key.is_active = False
        self.api_key.save()
        self.auth()
        response = self.client.get(self.URL)
        data = response.json()
        active_key_ids = [k["id"] for k in data["keys"]]
        self.assertNotIn(self.api_key.id, active_key_ids)

    def test_sync_keys_updates_timestamps(self):
        self.auth()
        self.assertIsNone(self.gateway.last_key_sync_at)
        self.client.get(self.URL)
        self.gateway.refresh_from_db()
        self.assertIsNotNone(self.gateway.last_key_sync_at)
        self.assertIsNotNone(self.gateway.last_seen_at)

    def test_sync_keys_no_auth_401(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 401)


class TestPushAuditEndpoint(GatewaySyncTestCase):
    URL = "/gateway-sync/v1/audit"

    def _entry(self, **overrides):
        base = {
            "tool_name": "testsys_users_list",
            "tool_type": "system_read",
            "duration_ms": 100,
            "success": True,
            "timestamp": timezone.now().isoformat(),
        }
        base.update(overrides)
        return base

    def test_push_audit_single_entry(self):
        self.auth()
        response = self.client.post(
            self.URL,
            {"entries": [self._entry()]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["received"], 1)
        self.assertEqual(GatewayAuditLog.objects.count(), 1)

    def test_push_audit_multiple_entries(self):
        self.auth()
        entries = [
            self._entry(tool_name="testsys_users_list"),
            self._entry(tool_name="testsys_users_create", tool_type="system_write"),
            self._entry(tool_name="testsys_projects_list"),
        ]
        response = self.client.post(self.URL, {"entries": entries}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["received"], 3)
        self.assertEqual(GatewayAuditLog.objects.count(), 3)

    def test_push_audit_validates_fields(self):
        self.auth()
        # Missing required 'tool_name' and 'tool_type'
        response = self.client.post(
            self.URL,
            {"entries": [{"duration_ms": 100}]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_push_audit_updates_timestamps(self):
        self.auth()
        self.assertIsNone(self.gateway.last_audit_push_at)
        self.client.post(self.URL, {"entries": [self._entry()]}, format="json")
        self.gateway.refresh_from_db()
        self.assertIsNotNone(self.gateway.last_audit_push_at)
        self.assertIsNotNone(self.gateway.last_seen_at)

    def test_push_audit_no_auth_401(self):
        response = self.client.post(
            self.URL,
            {"entries": [self._entry()]},
            format="json",
        )
        self.assertEqual(response.status_code, 401)


class TestPushHealthEndpoint(GatewaySyncTestCase):
    URL = "/gateway-sync/v1/health"

    def test_push_health_updates_fields(self):
        self.auth()
        response = self.client.post(
            self.URL,
            {
                "status": "healthy",
                "version": "1.2.3",
                "hostname": "gw-prod-01",
                "active_sessions": 5,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.gateway.refresh_from_db()
        self.assertEqual(self.gateway.version, "1.2.3")
        self.assertEqual(self.gateway.hostname, "gw-prod-01")
        self.assertEqual(self.gateway.active_sessions, 5)

    def test_push_health_credential_status(self):
        self.auth()
        cred_status = {"testsys": True, "jira": False}
        response = self.client.post(
            self.URL,
            {
                "status": "healthy",
                "credential_status": cred_status,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.gateway.refresh_from_db()
        self.assertEqual(self.gateway.credential_status, cred_status)

    def test_push_health_updates_last_seen(self):
        self.auth()
        self.assertIsNone(self.gateway.last_seen_at)
        self.client.post(
            self.URL,
            {"status": "healthy"},
            format="json",
        )
        self.gateway.refresh_from_db()
        self.assertIsNotNone(self.gateway.last_seen_at)

    def test_push_health_degraded_logged(self):
        self.auth()
        response = self.client.post(
            self.URL,
            {"status": "degraded", "version": "1.0.0"},
            format="json",
        )
        # Should not crash, just log a warning
        self.assertEqual(response.status_code, 200)

    def test_push_health_no_auth_401(self):
        response = self.client.post(
            self.URL,
            {"status": "healthy"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
