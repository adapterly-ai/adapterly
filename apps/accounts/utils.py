def get_active_account(request):
    """
    Helper function to get the active account from the request.
    """
    if hasattr(request, "active_account_user") and request.active_account_user:
        return request.active_account_user.account
    return None


def get_active_account_id(request):
    """
    Helper function to get the active account ID from the request.
    """
    if hasattr(request, "active_account_id") and request.active_account_id:
        return request.active_account_id
    return None


def get_active_account_user(request):
    """
    Helper function to get the active AccountUser from the request.
    Falls back to database lookup if not found on request (e.g. in tests).
    """
    if hasattr(request, "active_account_user") and request.active_account_user:
        return request.active_account_user

    if hasattr(request, "user") and request.user.is_authenticated:
        from apps.accounts.models import AccountUser

        return AccountUser.objects.filter(user=request.user, is_current_active=True).select_related("account").first()

    return None
