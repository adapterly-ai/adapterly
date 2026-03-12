"""Tests for gateway_core.diagnostics — error classification."""

from gateway_core.diagnostics import diagnose_error


class TestDiagnoseError:
    def _diag(self, status_code=None, error="", error_data=None, **kwargs):
        return diagnose_error(
            system_alias="testsys",
            tool_name="testsys_users_list",
            action_name="list",
            error_result={
                "status_code": status_code,
                "error": error,
                "error_data": error_data or {},
            },
            **kwargs,
        )

    # -- 401/403 variants --

    def test_401_token_expired(self):
        d = self._diag(status_code=401, error="Token expired")
        assert d["category"] == "auth_expired"
        assert d["severity"] == "high"

    def test_401_expired_with_drf_credentials(self):
        class FakeCreds:
            username = "user"
            password = "pass"
            oauth_refresh_token = None

        d = self._diag(status_code=401, error="token has expired", account_system=FakeCreds())
        assert d["category"] == "auth_expired"
        assert d["has_fix"] is True
        assert d["fix_action"]["type"] == "refresh_drf_token"

    def test_401_expired_with_oauth_refresh(self):
        class FakeCreds:
            username = None
            password = None
            oauth_refresh_token = "refresh-tok"

        d = self._diag(status_code=403, error="JWT expired", account_system=FakeCreds())
        assert d["category"] == "auth_expired"
        assert d["has_fix"] is True
        assert d["fix_action"]["type"] == "refresh_oauth"

    def test_403_permission(self):
        d = self._diag(status_code=403, error="Insufficient permissions")
        assert d["category"] == "auth_permissions"
        assert d["severity"] == "high"

    def test_401_generic(self):
        d = self._diag(status_code=401, error="Bad credentials")
        assert d["category"] == "auth_invalid"
        assert d["has_fix"] is True
        assert d["fix_action"]["type"] == "check_credentials"

    # -- 404 --

    def test_404_with_project_param(self):
        d = self._diag(
            status_code=404,
            error="Not found",
            request_params={"project_id": "123"},
        )
        assert d["category"] == "not_found_mapping"
        assert d["has_fix"] is True

    def test_404_path(self):
        d = self._diag(status_code=404, error="Not found")
        assert d["category"] == "not_found_path"
        assert d["has_fix"] is False

    # -- 400/422 --

    def test_422_missing_required(self):
        d = self._diag(status_code=422, error="Field 'name' is required")
        assert d["category"] == "validation_missing"

    def test_400_validation_type(self):
        d = self._diag(status_code=400, error="Invalid value for field 'age'")
        assert d["category"] == "validation_type"

    # -- 429 --

    def test_429_rate_limit(self):
        d = self._diag(status_code=429, error="Too many requests")
        assert d["category"] == "rate_limit"
        assert d["severity"] == "low"
        assert d["has_fix"] is True

    def test_429_with_retry_after(self):
        d = self._diag(
            status_code=429,
            error="Rate limit",
            error_data={"Retry-After": "30"},
        )
        assert d["category"] == "rate_limit"
        assert "30" in d["fix_description"]

    # -- 5xx --

    def test_500_server_error(self):
        d = self._diag(status_code=500, error="Internal server error")
        assert d["category"] == "server_error"
        assert d["severity"] == "high"

    def test_502_server_error(self):
        d = self._diag(status_code=502, error="Bad gateway")
        assert d["category"] == "server_error"

    # -- No status code --

    def test_timeout(self):
        d = self._diag(error="Request timed out")
        assert d["category"] == "timeout"
        assert d["severity"] == "medium"

    def test_connection_error(self):
        d = self._diag(error="Connection refused by remote host")
        assert d["category"] == "connection"
        assert d["severity"] == "high"

    def test_unknown(self):
        d = self._diag(status_code=418, error="I'm a teapot")
        assert d["category"] == "unknown"
        assert d["severity"] == "medium"

    # -- Output structure --

    def test_output_keys(self):
        d = self._diag(status_code=500, error="boom")
        expected_keys = {
            "category",
            "severity",
            "diagnosis_summary",
            "diagnosis_detail",
            "status_code",
            "error_data",
            "has_fix",
            "fix_description",
            "fix_action",
        }
        assert set(d.keys()) == expected_keys

    def test_summary_truncated_at_500(self):
        d = self._diag(status_code=418, error="x" * 1000)
        assert len(d["diagnosis_summary"]) <= 500
