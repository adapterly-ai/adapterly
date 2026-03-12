from django.urls import include, path
from rest_framework import routers

from apps.accounts.api.views import (
    AccountUserViewSet,
    AccountViewSet,
    DeviceAuthInitiateView,
    DeviceAuthStatusView,
)

router = routers.DefaultRouter()
router.register(r"accounts", AccountViewSet, basename="account")
router.register(r"account-users", AccountUserViewSet, basename="accountuser")

urlpatterns = [
    path("", include(router.urls)),
    path("auth/device/", DeviceAuthInitiateView.as_view(), name="device-auth-initiate"),
    path("auth/device/<uuid:device_code>/status/", DeviceAuthStatusView.as_view(), name="device-auth-status"),
]
