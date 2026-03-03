"""Tests for gateway_core.config — DeploymentMode and helpers."""

from gateway_core.config import DeploymentMode, get_deployment_mode, is_control_plane, is_gateway, is_monolith


class TestDeploymentMode:
    def test_default_is_monolith(self, monkeypatch):
        monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)
        assert get_deployment_mode() == DeploymentMode.MONOLITH

    def test_gateway_mode(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_MODE", "gateway")
        assert get_deployment_mode() == DeploymentMode.GATEWAY

    def test_control_plane_mode(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_MODE", "control_plane")
        assert get_deployment_mode() == DeploymentMode.CONTROL_PLANE

    def test_unknown_value_falls_back_to_monolith(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_MODE", "banana")
        assert get_deployment_mode() == DeploymentMode.MONOLITH

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_MODE", "GATEWAY")
        assert get_deployment_mode() == DeploymentMode.GATEWAY

    def test_helper_is_monolith(self, monkeypatch):
        monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)
        assert is_monolith() is True
        assert is_gateway() is False
        assert is_control_plane() is False

    def test_helper_is_gateway(self, monkeypatch):
        monkeypatch.setenv("DEPLOYMENT_MODE", "gateway")
        assert is_gateway() is True
        assert is_monolith() is False
