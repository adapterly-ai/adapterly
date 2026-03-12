from django.contrib.auth import get_user_model
from django.utils.deprecation import MiddlewareMixin

from apps.accounts.models import AccountUser

User = get_user_model()


class ActiveAccountMiddleware(MiddlewareMixin):
    """
    Middleware that manages the user's active account via AccountUser.is_current_active field.
    """

    def process_request(self, request):
        """
        Set the active account on the request object based on AccountUser.is_current_active.
        """
        if request.user.is_authenticated:
            active_account_user = (
                AccountUser.objects.filter(user=request.user, is_current_active=True).select_related("account").first()
            )

            if active_account_user:
                request.active_account_id = active_account_user.account.id
                request.active_account_name = active_account_user.account.name
                request.active_account_user = active_account_user
                request.account = active_account_user.account
            else:
                # If no active account, set the first account as active
                first_account_user = AccountUser.objects.filter(user=request.user).select_related("account").first()

                if first_account_user:
                    first_account_user.is_current_active = True
                    first_account_user.save()

                    request.active_account_id = first_account_user.account.id
                    request.active_account_name = first_account_user.account.name
                    request.active_account_user = first_account_user
                    request.account = first_account_user.account
                else:
                    # If user has no accounts, redirect to welcome page
                    request.active_account_id = None
                    request.active_account_name = None
                    request.active_account_user = None
                    request.account = None

                    # Don't redirect if already on welcome page or API endpoints
                    if (
                        not request.path.startswith("/account/welcome")
                        and not request.path.startswith("/api/")
                        and not request.path.startswith("/admin/")
                        and not request.path.startswith("/auth/")
                    ):
                        from django.shortcuts import redirect

                        return redirect("account_welcome")
        else:
            request.active_account_id = None
            request.active_account_name = None
            request.active_account_user = None
            request.account = None
