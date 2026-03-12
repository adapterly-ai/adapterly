from django_filters import rest_framework as filters

from apps.accounts.models import Account, AccountUser


class AccountFilter(filters.FilterSet):
    """
    Filter for Account models.
    Restricts accounts based on user permissions.
    """

    class Meta:
        model = Account
        fields = ["name"]

    def filter_queryset(self, queryset):
        """
        Override filter_queryset to add account filtering.
        Uses active account if available, otherwise all user's accounts.
        """
        if self.request.user.is_superuser:
            return super().filter_queryset(queryset)

        active_account_user = getattr(self.request, "active_account_user", None)

        if active_account_user:
            queryset = queryset.filter(id=active_account_user.account.id)
        else:
            try:
                user_accounts = AccountUser.objects.filter(user=self.request.user).values_list("account", flat=True)

                if not user_accounts:
                    return queryset.none()

                queryset = queryset.filter(id__in=user_accounts)

            except AccountUser.DoesNotExist:
                return queryset.none()

        return super().filter_queryset(queryset)


class AccountUserFilter(filters.FilterSet):
    """
    Filter for AccountUser models.
    Restricts AccountUsers based on user permissions.
    """

    class Meta:
        model = AccountUser
        fields = ["account", "is_admin", "is_current_active"]

    def filter_queryset(self, queryset):
        """
        Override filter_queryset to add account filtering.
        Uses active account if available, otherwise all user's accounts.
        """
        if self.request.user.is_superuser:
            return super().filter_queryset(queryset)

        active_account_user = getattr(self.request, "active_account_user", None)

        if active_account_user:
            queryset = queryset.filter(account=active_account_user.account)
        else:
            try:
                user_accounts = AccountUser.objects.filter(user=self.request.user).values_list("account", flat=True)

                if not user_accounts:
                    return queryset.none()

                queryset = queryset.filter(account__in=user_accounts)

            except AccountUser.DoesNotExist:
                return queryset.none()

        return super().filter_queryset(queryset)
