from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.accounts.api.filters import AccountFilter, AccountUserFilter
from apps.accounts.api.serializers import AccountSerializer, AccountUserSerializer, CreateAccountUserSerializer
from apps.accounts.models import Account, AccountUser, DeviceAuthorization

User = get_user_model()


class AccountViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing Account models.
    """

    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = AccountFilter
    pagination_class = PageNumberPagination

    def get_queryset(self):
        """
        Return all accounts - filter handles restrictions.
        """
        return Account.objects.order_by("-id")

    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        """
        Set account as active for the user.
        POST /api/accounts/{id}/set-active/
        """
        account = self.get_object()

        if not request.user.is_superuser:
            account_user = AccountUser.objects.filter(account=account, user=request.user).first()
            if not account_user:
                raise PermissionDenied("You do not have permission to access this account.")
        else:
            account_user, created = AccountUser.objects.get_or_create(
                account=account, user=request.user, defaults={"is_admin": True}
            )

        account_user.is_current_active = True
        account_user.save()

        return Response(
            {
                "message": f'Account "{account.name}" set as active.',
                "active_account_id": account.id,
                "active_account_name": account.name,
            }
        )

    @action(detail=False, methods=["get"], url_path="active")
    def get_active(self, request):
        """
        Get the active account for the user.
        GET /api/accounts/active/
        """
        active_account_user = (
            AccountUser.objects.filter(user=request.user, is_current_active=True).select_related("account").first()
        )

        if active_account_user:
            serializer = AccountSerializer(active_account_user.account)
            return Response(
                {
                    "active_account": serializer.data,
                    "active_account_id": active_account_user.account.id,
                    "active_account_name": active_account_user.account.name,
                    "is_admin": active_account_user.is_admin,
                }
            )

        return Response(
            {"active_account": None, "active_account_id": None, "active_account_name": None, "is_admin": False}
        )

    @action(detail=True, methods=["get"], url_path="users")
    def get_users(self, request, pk=None):
        """
        Get account users.
        GET /api/accounts/{id}/users/
        """
        account = self.get_object()

        if not request.user.is_superuser:
            if not AccountUser.objects.filter(account=account, user=request.user).exists():
                raise PermissionDenied("You do not have permission to view this account's users.")

        users = AccountUser.objects.filter(account=account)
        serializer = AccountUserSerializer(users, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="users")
    def add_user(self, request, pk=None):
        """
        Add user to account.
        POST /api/accounts/{id}/users/
        """
        account = self.get_object()

        if not request.user.is_superuser:
            account_user = AccountUser.objects.filter(account=account, user=request.user).first()
            if not account_user or not account_user.is_admin:
                raise PermissionDenied("You do not have permission to add users to this account.")

        serializer = CreateAccountUserSerializer(data={"account_id": account.id, **request.data})

        if serializer.is_valid():
            account_user = serializer.save()
            response_serializer = AccountUserSerializer(account_user)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["delete"], url_path="users/(?P<user_id>[^/.]+)/")
    def remove_user(self, request, pk=None, user_id=None):
        """
        Remove user from account.
        DELETE /api/accounts/{id}/users/{user_id}/
        """
        account = self.get_object()

        if not request.user.is_superuser:
            account_user = AccountUser.objects.filter(account=account, user=request.user).first()
            if not account_user or not account_user.is_admin:
                raise PermissionDenied("You do not have permission to remove users from this account.")

        try:
            account_user = AccountUser.objects.get(account=account, user_id=user_id)
            account_user.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except AccountUser.DoesNotExist:
            return Response({"error": "User not found in account."}, status=status.HTTP_404_NOT_FOUND)


class AccountUserViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AccountUser models.
    """

    serializer_class = AccountUserSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = AccountUserFilter
    pagination_class = PageNumberPagination

    def get_queryset(self):
        """
        Return all AccountUsers - filter handles restrictions.
        """
        return AccountUser.objects.select_related("account", "user").order_by("-id")

    def perform_create(self, serializer):
        """
        Ensure new AccountUser is created correctly.
        """
        if self.request.user.is_superuser:
            serializer.save()
        else:
            account_id = serializer.validated_data.get("account").id
            account_user = AccountUser.objects.filter(account_id=account_id, user=self.request.user).first()

            if not account_user or not account_user.is_admin:
                raise PermissionDenied("You do not have permission to add users to this account.")

            serializer.save()

    def perform_update(self, serializer):
        """
        Ensure user can only update AccountUsers they have permissions for.
        """
        account_user = self.get_object()

        if self.request.user.is_superuser:
            serializer.save()
        else:
            user_account_user = AccountUser.objects.filter(account=account_user.account, user=self.request.user).first()

            if not user_account_user or not user_account_user.is_admin:
                raise PermissionDenied("You do not have permission to update this AccountUser.")

            serializer.save()

    def perform_destroy(self, instance):
        """
        Ensure user can only delete AccountUsers they have permissions for.
        """
        if self.request.user.is_superuser:
            instance.delete()
        else:
            user_account_user = AccountUser.objects.filter(account=instance.account, user=self.request.user).first()

            if not user_account_user or not user_account_user.is_admin:
                raise PermissionDenied("You do not have permission to delete this AccountUser.")

            instance.delete()


class DeviceAuthThrottle(AnonRateThrottle):
    rate = "20/hour"


class DeviceAuthInitiateView(APIView):
    """
    POST /api/auth/device/
    Create a new device authorization request (anonymous).
    Returns device_code, user_code, verification_url, expires_in, poll_interval.
    """

    permission_classes = [AllowAny]
    throttle_classes = [DeviceAuthThrottle]

    def post(self, request):
        # Cleanup expired authorizations
        DeviceAuthorization.cleanup_expired()

        # Rate limit: max 10 pending per IP
        client_ip = self._get_client_ip(request)
        pending_count = DeviceAuthorization.objects.filter(
            client_ip=client_ip,
            status=DeviceAuthorization.Status.PENDING,
        ).count()
        if pending_count >= 10:
            return Response(
                {"error": "Too many pending authorizations from this IP."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        client_name = request.data.get("client_name", "Agent Terminal")

        auth = DeviceAuthorization(
            client_name=client_name[:255],
            client_ip=client_ip,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        auth.save()

        verification_url = request.build_absolute_uri(f"/account/authorize/{auth.user_code}/")

        return Response(
            {
                "device_code": str(auth.device_code),
                "user_code": auth.user_code,
                "verification_url": verification_url,
                "expires_in": 600,
                "poll_interval": 5,
            },
            status=status.HTTP_201_CREATED,
        )

    def _get_client_ip(self, request):
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


class DeviceAuthStatusView(APIView):
    """
    GET /api/auth/device/<device_code>/status/
    Poll for device authorization status (anonymous).
    """

    permission_classes = [AllowAny]
    throttle_classes = [DeviceAuthThrottle]

    def get(self, request, device_code):
        try:
            auth = DeviceAuthorization.objects.get(device_code=device_code)
        except DeviceAuthorization.DoesNotExist:
            return Response({"error": "Invalid device code."}, status=status.HTTP_404_NOT_FOUND)

        # Increment poll count
        auth.poll_count += 1
        auth.save(update_fields=["poll_count"])

        # Check expiry
        if auth.is_expired and auth.status == DeviceAuthorization.Status.PENDING:
            auth.status = DeviceAuthorization.Status.EXPIRED
            auth.save(update_fields=["status"])

        response = {"status": auth.status}

        if auth.status == DeviceAuthorization.Status.APPROVED:
            response["token"] = auth.token

        return Response(response)
