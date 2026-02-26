from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from rest_framework.authtoken.models import Token

from apps.core.throttles import ratelimit

from .models import AccountUser, DeviceAuthorization
from .utils import get_active_account, get_active_account_user


@login_required
def account_dashboard(request):
    """
    Account page showing:
    - Account details (name, creation date)
    - User list
    - Option to add/remove users
    - Option to set admin rights
    """
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        # Redirect to switch page instead of dashboard to avoid infinite loop
        return redirect("switch_account")

    if not active_account_user.is_admin:
        messages.error(request, "You do not have permission to view the account page.")
        return redirect("index")

    account_users = AccountUser.objects.filter(account=active_account).select_related("user")

    # Get all user's accounts (for account switching)
    user_accounts = AccountUser.objects.filter(user=request.user).select_related("account")

    # Get pending invitations
    from apps.accounts.models import UserInvitation

    pending_invitations = UserInvitation.objects.filter(account=active_account, is_used=False).order_by("-created_at")

    from django.utils import timezone

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "account_users": account_users,
        "user_accounts": user_accounts,
        "pending_invitations": pending_invitations,
        "now": timezone.now(),
    }

    return render(request, "accounts/dashboard.html", context)


@login_required
def switch_account(request):
    """
    Account switching page showing:
    - User's accounts
    - Option to switch active account
    """
    user_accounts = AccountUser.objects.filter(user=request.user).select_related("account")

    context = {
        "user_accounts": user_accounts,
        "active_account": get_active_account(request),
    }

    return render(request, "accounts/switch.html", context)


@login_required
def account_settings(request):
    """
    Account settings page showing:
    - Account details
    - Users
    - Permissions
    - Option to add/remove users (if admin)
    """
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        return redirect("switch_account")

    account_users = AccountUser.objects.filter(account=active_account).select_related("user")

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "account_users": account_users,
    }

    return render(request, "accounts/settings.html", context)


@login_required
@require_POST
def switch_account_ajax(request):
    """
    AJAX endpoint for switching accounts.
    """
    account_id = request.POST.get("account_id")

    if not account_id:
        return JsonResponse({"error": "Account ID is missing"}, status=400)

    try:
        account_user = AccountUser.objects.get(account_id=account_id, user=request.user)

        account_user.is_current_active = True
        account_user.save()

        return JsonResponse(
            {"success": True, "account_name": account_user.account.name, "account_id": account_user.account.id}
        )

    except AccountUser.DoesNotExist:
        return JsonResponse({"error": "You do not have permission to access this account"}, status=403)


@login_required
@require_POST
def remove_user_from_account(request):
    """
    AJAX endpoint for removing a user from an account.
    """
    account_id = request.POST.get("account_id")
    user_id = request.POST.get("user_id")

    if not account_id or not user_id:
        return JsonResponse({"error": "Account ID or User ID is missing"}, status=400)

    try:
        active_account_user = get_active_account_user(request)
        if not active_account_user or not active_account_user.is_admin:
            return JsonResponse({"error": "You do not have admin permissions"}, status=403)

        if str(active_account_user.account.id) != str(account_id):
            return JsonResponse({"error": "You can only remove users from the active account"}, status=403)

        if str(user_id) == str(request.user.id):
            return JsonResponse({"error": "You cannot remove yourself from the account"}, status=400)

        account_user = AccountUser.objects.get(account_id=account_id, user_id=user_id)
        username = account_user.user.username
        account_user.delete()

        return JsonResponse({"success": True, "message": f"User {username} removed from account"})

    except AccountUser.DoesNotExist:
        return JsonResponse({"error": "User not found in account"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def toggle_admin_status(request):
    """
    AJAX endpoint for toggling admin status.
    """
    account_id = request.POST.get("account_id")
    user_id = request.POST.get("user_id")

    if not account_id or not user_id:
        return JsonResponse({"error": "Account ID or User ID is missing"}, status=400)

    try:
        active_account_user = get_active_account_user(request)
        if not active_account_user or not active_account_user.is_admin:
            return JsonResponse({"error": "You do not have admin permissions"}, status=403)

        if str(active_account_user.account.id) != str(account_id):
            return JsonResponse({"error": "You can only change admin status in the active account"}, status=403)

        account_user = AccountUser.objects.get(account_id=account_id, user_id=user_id)
        account_user.is_admin = not account_user.is_admin
        account_user.save()

        return JsonResponse(
            {
                "success": True,
                "message": f"Admin status {'enabled' if account_user.is_admin else 'disabled'} for {account_user.user.username}",
                "is_admin": account_user.is_admin,
            }
        )

    except AccountUser.DoesNotExist:
        return JsonResponse({"error": "User not found in account"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@ratelimit(key="user", rate="10/hour")
def invite_user(request):
    """
    Invite user to account.
    Rate limited: 10 invitations/hour per user.

    Shows a form where you can:
    - Send invitation via email (if user is not registered)
    - Add directly (if user is already registered)
    """
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        messages.error(request, "You don't have permission to invite users.")
        return redirect("account_dashboard")

    if request.method == "POST":
        email = request.POST.get("email")
        is_admin = request.POST.get("is_admin") == "on"

        if not email:
            messages.error(request, "Email is required.")
            return redirect("invite_user")

        # Check if user is already registered
        from django.contrib.auth import get_user_model

        User = get_user_model()

        try:
            existing_user = User.objects.get(email=email)
            # User is already registered - add directly to account
            account_user, created = AccountUser.objects.get_or_create(
                account=active_account, user=existing_user, defaults={"is_admin": is_admin}
            )

            if created:
                messages.success(request, f"User {existing_user.username} added to account.")
            else:
                messages.info(request, f"User {existing_user.username} is already a member of this account.")

        except User.DoesNotExist:
            # User is not registered - send invitation
            from .models import UserInvitation

            invitation, created = UserInvitation.objects.get_or_create(
                email=email, account=active_account, defaults={"invited_by": request.user, "is_admin": is_admin}
            )

            if created:
                # Send invitation email
                success = invitation.send_invitation_email(request)
                if success:
                    messages.success(request, f"Invitation sent to {email}.")
                else:
                    messages.warning(
                        request, "Invitation created but email sending failed. Please check email configuration."
                    )
            else:
                # Resend invitation if not used
                if not invitation.is_used:
                    success = invitation.send_invitation_email(request)
                    if success:
                        messages.info(request, f"Invitation resent to {email}.")
                    else:
                        messages.warning(request, "Invitation exists but email sending failed.")
                else:
                    messages.info(request, f"An invitation has already been sent and used for {email}.")

        return redirect("account_dashboard")

    return render(
        request,
        "accounts/invite.html",
        {
            "active_account": active_account,
        },
    )


def accept_invitation(request, token):
    """
    Handle invitation acceptance when user clicks invitation link.
    """
    try:
        from .models import UserInvitation

        invitation = UserInvitation.objects.get(token=token, is_used=False)

        # Check if invitation has expired
        if invitation.is_expired():
            messages.error(request, "This invitation has expired.")
            return redirect("account_login")

        if request.method == "POST":
            # User accepts invitation and registers
            username = request.POST.get("username")
            password1 = request.POST.get("password1")
            password2 = request.POST.get("password2")

            if password1 != password2:
                messages.error(request, "Passwords do not match.")
                return render(
                    request,
                    "accounts/accept_invitation.html",
                    {"invitation": invitation, "error": "Passwords do not match"},
                )

            # Check if username already exists
            from django.contrib.auth import get_user_model

            User = get_user_model()

            if User.objects.filter(username=username).exists():
                return render(
                    request,
                    "accounts/accept_invitation.html",
                    {"invitation": invitation, "error": "Username is already taken"},
                )

            # Create user, AccountUser, and mark invitation - all in one transaction
            try:
                with transaction.atomic():
                    user = User.objects.create_user(username=username, email=invitation.email, password=password1)

                    # Create AccountUser
                    AccountUser.objects.create(
                        account=invitation.account,
                        user=user,
                        is_admin=invitation.is_admin,
                        is_current_active=True,  # Set as active
                    )

                    # Mark invitation as used
                    invitation.is_used = True
                    invitation.save()

                messages.success(request, f"Welcome to {invitation.account.name}! You can now log in.")
                return redirect("account_login")

            except Exception as e:
                messages.error(request, f"Error creating account: {str(e)}")
                return render(request, "accounts/accept_invitation.html", {"invitation": invitation, "error": str(e)})

        return render(
            request,
            "accounts/accept_invitation.html",
            {
                "invitation": invitation,
            },
        )

    except UserInvitation.DoesNotExist:
        messages.error(request, "This invitation is not valid or has already been used.")
        return redirect("account_login")


@login_required
def change_account_name(request):
    """
    Change the name of the active account.
    """
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user or not active_account_user.is_admin:
        messages.error(request, "You don't have permission to change the account name.")
        return redirect("account_dashboard")

    if request.method == "POST":
        new_name = request.POST.get("account_name", "").strip()

        if not new_name:
            messages.error(request, "Account name cannot be empty.")
            return redirect("account_dashboard")

        active_account.name = new_name
        active_account.save()
        messages.success(request, f"Account name changed to '{new_name}'.")
        return redirect("account_dashboard")

    return redirect("account_dashboard")


@login_required
def user_profile(request):
    """
    User profile page with personal settings.
    Shows user info, account switching, password change, etc.
    """
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    # Get all user's accounts for switching
    user_accounts = AccountUser.objects.filter(user=request.user).select_related("account")

    # Count admin accounts
    admin_count = user_accounts.filter(is_admin=True).count()

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "user_accounts": user_accounts,
        "admin_count": admin_count,
    }

    return render(request, "accounts/user_profile.html", context)


@login_required
def change_password(request):
    """
    Allow user to change their password.
    """
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.forms import PasswordChangeForm

    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Keep user logged in
            messages.success(request, "Your password has been changed successfully!")
            return redirect("account_dashboard")
        else:
            for error in form.errors.values():
                messages.error(request, error)
    else:
        form = PasswordChangeForm(request.user)

    return render(
        request,
        "accounts/change_password.html",
        {
            "form": form,
            "active_account": get_active_account(request),
            "active_account_user": get_active_account_user(request),
        },
    )


@login_required
def account_welcome(request):
    """
    Welcome page for new users who don't have an account yet.
    This page will trigger the automatic account creation signal.
    """
    # Try to get or create account for user
    from apps.accounts.models import Account, AccountUser

    user_accounts = AccountUser.objects.filter(user=request.user).select_related("account")

    # If user still doesn't have an account, create one manually
    if not user_accounts.exists():
        with transaction.atomic():
            account = Account.objects.create(name=f"{request.user.username}'s Account")
            AccountUser.objects.create(account=account, user=request.user, is_admin=True, is_current_active=True)
        messages.success(request, f"Welcome! We've created your personal account '{account.name}'.")
        return redirect("/dashboard/")

    # If user has accounts now, redirect to home
    if user_accounts.exists():
        messages.success(request, "Welcome back!")
        return redirect("/dashboard/")

    return render(
        request,
        "accounts/welcome.html",
        {
            "user": request.user,
        },
    )


@login_required
def create_account(request):
    """
    Create a new account for the current user.
    The user becomes admin of the new account and it becomes active.
    """
    if request.method == "POST":
        account_name = request.POST.get("account_name", "").strip()

        if not account_name:
            messages.error(request, "Account name is required.")
            return redirect("create_account")

        with transaction.atomic():
            from apps.accounts.models import Account

            account = Account.objects.create(name=account_name)
            AccountUser.objects.create(
                account=account,
                user=request.user,
                is_admin=True,
                is_current_active=True,
            )

        messages.success(request, f"Account '{account_name}' created successfully!")
        return redirect("account_dashboard")

    return render(
        request,
        "accounts/create_account.html",
        {
            "active_account": get_active_account(request),
            "active_account_user": get_active_account_user(request),
        },
    )


@login_required
def api_token(request):
    """
    Show or generate a DRF auth token for the current user.

    Useful for users who authenticate via Google OAuth and need a token
    for external integrations (e.g., agent-view wizard).
    """
    token, _ = Token.objects.get_or_create(user=request.user)
    regenerated = False

    if request.method == "POST" and "regenerate" in request.POST:
        token.delete()
        token = Token.objects.create(user=request.user)
        regenerated = True
        messages.success(request, "API token regenerated.")

    return render(
        request,
        "accounts/api_token.html",
        {
            "token": token.key,
            "regenerated": regenerated,
        },
    )


@login_required
def device_authorize(request, user_code):
    """
    Device authorization approval page.
    GET: show approval form with client info.
    POST: approve or deny the authorization.
    """
    try:
        auth = DeviceAuthorization.objects.get(user_code=user_code.upper())
    except DeviceAuthorization.DoesNotExist:
        messages.error(request, "Invalid authorization code.")
        return redirect("index")

    # Check expiry
    if auth.is_expired and auth.status == DeviceAuthorization.Status.PENDING:
        auth.status = DeviceAuthorization.Status.EXPIRED
        auth.save(update_fields=["status"])

    if auth.status != DeviceAuthorization.Status.PENDING:
        messages.error(request, f"This authorization request has already been {auth.status}.")
        return redirect("index")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "approve":
            # Get or create DRF token for the user
            token, _ = Token.objects.get_or_create(user=request.user)

            auth.status = DeviceAuthorization.Status.APPROVED
            auth.user = request.user
            auth.token = token.key
            auth.save(update_fields=["status", "user", "token"])

            return render(
                request,
                "accounts/device_authorized.html",
                {"auth": auth, "approved": True},
            )

        elif action == "deny":
            auth.status = DeviceAuthorization.Status.DENIED
            auth.user = request.user
            auth.save(update_fields=["status", "user"])

            return render(
                request,
                "accounts/device_authorized.html",
                {"auth": auth, "approved": False},
            )

    return render(
        request,
        "accounts/device_authorize.html",
        {
            "auth": auth,
            "user_code": auth.user_code,
            "client_name": auth.client_name,
        },
    )
