"""
Gateway Sync API URL configuration.

All endpoints are under /gateway-sync/v1/
"""

from django.urls import path

from .api import views

app_name = "gateways"

urlpatterns = [
    path("register", views.register, name="gateway-register"),
    path("specs", views.sync_specs, name="gateway-sync-specs"),
    path("keys", views.sync_keys, name="gateway-sync-keys"),
    path("audit", views.push_audit, name="gateway-push-audit"),
    path("health", views.push_health, name="gateway-push-health"),
]
