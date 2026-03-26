"""Tests for adapterly.executor.engine helper functions."""

from __future__ import annotations

import pytest

from adapterly.crypto import configure_secret_key, encrypt_value
from adapterly.executor.engine import _extract_items, _resolve_variables, _substitute_path_params


@pytest.fixture(autouse=True)
def _setup_crypto():
    configure_secret_key("test-secret-key-for-pytest")
    yield


# ── _substitute_path_params ───────────────────────────────────────────────

class TestSubstitutePathParams:
    def test_single_param(self):
        params = {"project_id": "123", "limit": 10}
        result = _substitute_path_params("/projects/{project_id}/items", params)
        assert result == "/projects/123/items"
        # project_id should be consumed from params
        assert "project_id" not in params
        assert params["limit"] == 10

    def test_multiple_params(self):
        params = {"org": "acme", "repo": "web", "extra": "keep"}
        result = _substitute_path_params("/orgs/{org}/repos/{repo}", params)
        assert result == "/orgs/acme/repos/web"
        assert "org" not in params
        assert "repo" not in params
        assert params["extra"] == "keep"

    def test_no_placeholders(self):
        params = {"limit": 10}
        result = _substitute_path_params("/items", params)
        assert result == "/items"
        assert params == {"limit": 10}

    def test_empty_path(self):
        params = {"foo": "bar"}
        result = _substitute_path_params("", params)
        assert result == ""
        assert params == {"foo": "bar"}

    def test_none_path(self):
        """None path should be handled (returns empty string)."""
        params = {}
        result = _substitute_path_params(None, params)
        assert result == ""

    def test_integer_param_value(self):
        params = {"id": 42}
        result = _substitute_path_params("/items/{id}", params)
        assert result == "/items/42"
        assert "id" not in params

    def test_unmatched_placeholder_stays(self):
        params = {}
        result = _substitute_path_params("/items/{missing}", params)
        assert result == "/items/{missing}"


# ── _extract_items ────────────────────────────────────────────────────────

class TestExtractItems:
    def test_explicit_data_field(self):
        data = {"results": [1, 2, 3], "total": 3}
        assert _extract_items(data, "results") == [1, 2, 3]

    def test_list_input(self):
        data = [{"id": 1}, {"id": 2}]
        assert _extract_items(data) == data

    def test_auto_detect_content(self):
        data = {"content": [{"a": 1}], "pageable": {}}
        assert _extract_items(data) == [{"a": 1}]

    def test_auto_detect_items(self):
        data = {"items": [1, 2], "next": None}
        assert _extract_items(data) == [1, 2]

    def test_auto_detect_data(self):
        data = {"data": [10, 20], "meta": {}}
        assert _extract_items(data) == [10, 20]

    def test_auto_detect_results(self):
        data = {"results": [{"x": 1}], "count": 1}
        assert _extract_items(data) == [{"x": 1}]

    def test_auto_detect_records(self):
        data = {"records": [{"r": 1}]}
        assert _extract_items(data) == [{"r": 1}]

    def test_empty_dict_returns_empty_list(self):
        assert _extract_items({}) == []

    def test_dict_without_known_fields(self):
        data = {"status": "ok", "message": "done"}
        assert _extract_items(data) == []

    def test_data_field_missing_falls_back(self):
        data = {"items": [1, 2]}
        # explicit data_field that doesn't exist falls to auto-detect
        assert _extract_items(data, "nonexistent") == [1, 2]

    def test_none_data_field(self):
        data = [1, 2, 3]
        assert _extract_items(data, None) == [1, 2, 3]

    def test_nested_list_not_auto_detected(self):
        """Only top-level known field names are detected."""
        data = {"deep": {"items": [1]}}
        assert _extract_items(data) == []

    def test_priority_order(self):
        """content comes before items in the detection order."""
        data = {"content": ["a"], "items": ["b"]}
        assert _extract_items(data) == ["a"]


# ── _resolve_variables ────────────────────────────────────────────────────

class TestResolveVariables:
    def test_no_variables(self):
        result = _resolve_variables("https://api.example.com", {}, {})
        assert result == "https://api.example.com"

    def test_credential_source(self):
        encrypted_domain = encrypt_value("mycompany")
        variables = {
            "domain": {"source": "credential", "field": "domain"},
        }
        credentials = {"domain": encrypted_domain}
        result = _resolve_variables("https://{domain}.atlassian.net", variables, credentials)
        assert result == "https://mycompany.atlassian.net"

    def test_default_source(self):
        variables = {
            "region": {"source": "static", "default": "eu-west-1"},
        }
        result = _resolve_variables("https://api.{region}.aws.com", variables, {})
        assert result == "https://api.eu-west-1.aws.com"

    def test_placeholder_not_in_url_is_skipped(self):
        variables = {
            "unused": {"source": "credential", "field": "unused"},
        }
        result = _resolve_variables("https://api.example.com", variables, {})
        assert result == "https://api.example.com"

    def test_missing_credential_replaces_with_empty(self):
        variables = {
            "domain": {"source": "credential", "field": "domain"},
        }
        result = _resolve_variables("https://{domain}.example.com", variables, {})
        assert result == "https://.example.com"

    def test_none_variables(self):
        result = _resolve_variables("https://example.com/{path}", None, {})
        assert result == "https://example.com/{path}"

    def test_multiple_variables(self):
        enc_org = encrypt_value("acme")
        enc_env = encrypt_value("prod")
        variables = {
            "org": {"source": "credential", "field": "org"},
            "env": {"source": "credential", "field": "env"},
        }
        credentials = {"org": enc_org, "env": enc_env}
        result = _resolve_variables("https://{org}.api.{env}.example.com", variables, credentials)
        assert result == "https://acme.api.prod.example.com"
