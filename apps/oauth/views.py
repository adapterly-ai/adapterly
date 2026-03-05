import hashlib
import json
import logging
from base64 import urlsafe_b64encode
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.mcp.models import MCPApiKey

from .models import AuthorizationCode, OAuthApplication

logger = logging.getLogger(__name__)

# Base URL for metadata endpoints
BASE_URL = "https://adapterly.ai"


def _error_redirect(redirect_uri, error, description, state=None):
    """Build OAuth2 error redirect."""
    params = {"error": error, "error_description": description}
    if state:
        params["state"] = state
    return redirect(f"{redirect_uri}?{urlencode(params)}")


def _error_json(error, description, status=400):
    """Return OAuth2 error JSON response."""
    return JsonResponse({"error": error, "error_description": description}, status=status)


def _verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """Verify PKCE code_verifier against stored code_challenge."""
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return computed == code_challenge
    elif method == "plain":
        return code_verifier == code_challenge
    return False


# ── Well-known metadata endpoints (RFC 8414 / RFC 9728) ──


@csrf_exempt
@require_GET
def authorization_server_metadata(request):
    """
    GET /.well-known/oauth-authorization-server

    OAuth 2.0 Authorization Server Metadata (RFC 8414).
    """
    return JsonResponse({
        "issuer": BASE_URL,
        "authorization_endpoint": f"{BASE_URL}/oauth/authorize/",
        "token_endpoint": f"{BASE_URL}/oauth/token/",
        "registration_endpoint": f"{BASE_URL}/oauth/register/",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    })


@csrf_exempt
@require_GET
def protected_resource_metadata(request, resource_path=""):
    """
    GET /.well-known/oauth-protected-resource[/<path>]

    OAuth 2.0 Protected Resource Metadata (RFC 9728).
    """
    resource = f"{BASE_URL}/mcp/v1/"
    if resource_path:
        resource = f"{BASE_URL}/{resource_path}"

    return JsonResponse({
        "resource": resource,
        "authorization_servers": [BASE_URL],
        "bearer_methods_supported": ["header"],
    })


# ── Authorization endpoint ──


@login_required
@require_http_methods(["GET", "POST"])
def authorize(request):
    """OAuth2 authorization endpoint with PKCE support."""
    client_id = request.GET.get("client_id") or request.POST.get("client_id")
    redirect_uri = request.GET.get("redirect_uri") or request.POST.get("redirect_uri")
    response_type = request.GET.get("response_type") or request.POST.get("response_type")
    state = request.GET.get("state") or request.POST.get("state", "")
    code_challenge = request.GET.get("code_challenge") or request.POST.get("code_challenge", "")
    code_challenge_method = request.GET.get("code_challenge_method") or request.POST.get("code_challenge_method", "S256")

    # Validate required params
    if not client_id or not redirect_uri:
        return render(request, "oauth/authorize.html", {
            "error": "Missing client_id or redirect_uri.",
        }, status=400)

    if response_type != "code":
        return render(request, "oauth/authorize.html", {
            "error": "Unsupported response_type. Only 'code' is supported.",
        }, status=400)

    # Look up application
    try:
        app = OAuthApplication.objects.get(client_id=client_id, is_active=True)
    except OAuthApplication.DoesNotExist:
        return render(request, "oauth/authorize.html", {
            "error": "Unknown application.",
        }, status=400)

    # Validate redirect_uri
    if redirect_uri != app.redirect_uri:
        return render(request, "oauth/authorize.html", {
            "error": "redirect_uri does not match registered URI.",
        }, status=400)

    # Check user has an active account
    account = getattr(request, "account", None)
    if not account:
        return render(request, "oauth/authorize.html", {
            "error": "No active account. Please set up your account first.",
        }, status=400)

    if request.method == "GET":
        return render(request, "oauth/authorize.html", {
            "app": app,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": response_type,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "account": account,
        })

    # POST — user clicked Authorize
    code = AuthorizationCode.objects.create(
        application=app,
        user=request.user,
        account=account,
        code=AuthorizationCode.generate_code(),
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method if code_challenge else "",
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    params = {"code": code.code}
    if state:
        params["state"] = state

    logger.info("OAuth code issued for app=%s user=%s account=%s", app.name, request.user, account)
    return redirect(f"{redirect_uri}?{urlencode(params)}")


# ── Token endpoint ──


def _parse_token_request(request):
    """Parse token request from form data or JSON body."""
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            data = {}
    else:
        data = request.POST
    return data


@csrf_exempt
@require_POST
def token(request):
    """OAuth2 token endpoint (server-to-server) with PKCE validation."""
    data = _parse_token_request(request)

    # Rate limiting: 20 req/min per client_id
    client_id = data.get("client_id", "")
    rate_key = f"oauth_token_rate:{client_id}"
    count = cache.get(rate_key, 0)
    if count >= 20:
        return _error_json("rate_limit_exceeded", "Too many requests. Try again later.", status=429)
    cache.set(rate_key, count + 1, timeout=60)

    grant_type = data.get("grant_type")
    client_secret = data.get("client_secret", "")
    code_value = data.get("code", "")
    redirect_uri = data.get("redirect_uri", "")
    code_verifier = data.get("code_verifier", "")

    if grant_type != "authorization_code":
        return _error_json("unsupported_grant_type", "Only authorization_code is supported.")

    if not client_id or not code_value:
        return _error_json("invalid_request", "Missing client_id or code.")

    # Validate client
    try:
        app = OAuthApplication.objects.get(client_id=client_id, is_active=True)
    except OAuthApplication.DoesNotExist:
        return _error_json("invalid_client", "Unknown client.", status=401)

    # client_secret is required if no PKCE, optional with PKCE
    if client_secret:
        if not app.verify_secret(client_secret):
            return _error_json("invalid_client", "Bad client_secret.", status=401)

    # Validate code
    try:
        auth_code = AuthorizationCode.objects.select_related("account", "user", "application").get(code=code_value)
    except AuthorizationCode.DoesNotExist:
        return _error_json("invalid_grant", "Unknown authorization code.")

    if auth_code.application_id != app.id:
        return _error_json("invalid_grant", "Code does not belong to this client.")

    if not auth_code.is_valid:
        return _error_json("invalid_grant", "Code is expired or already used.")

    if redirect_uri and redirect_uri != auth_code.redirect_uri:
        return _error_json("invalid_grant", "redirect_uri mismatch.")

    # PKCE validation
    if auth_code.code_challenge:
        if not code_verifier:
            return _error_json("invalid_grant", "code_verifier required (PKCE).")
        if not _verify_pkce(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method or "S256"):
            return _error_json("invalid_grant", "PKCE verification failed.")
    elif not client_secret:
        # No PKCE and no client_secret — reject
        return _error_json("invalid_client", "client_secret or PKCE required.", status=401)

    # Mark code as used
    auth_code.is_used = True
    auth_code.save(update_fields=["is_used"])

    # Create MCPApiKey as the access token
    key, prefix, key_hash = MCPApiKey.generate_key()
    api_key = MCPApiKey(
        account=auth_code.account,
        created_by=auth_code.user,
        name=f"OAuth: {app.name} ({auth_code.user.username})",
        key_prefix=prefix,
        key_hash=key_hash,
        mode=app.mode,
        is_active=True,
    )
    if app.profile:
        api_key.profile = app.profile
    if app.project:
        api_key.project = app.project
    elif auth_code.account.default_project:
        api_key.project = auth_code.account.default_project
    api_key.save()

    logger.info(
        "OAuth token issued for app=%s user=%s account=%s",
        app.name, auth_code.user, auth_code.account,
    )

    return JsonResponse({
        "access_token": key,
        "token_type": "Bearer",
    })


# ── Dynamic Client Registration (RFC 7591) ──

# Default account for dynamically registered clients
DEFAULT_REGISTRATION_ACCOUNT_ID = 1


@csrf_exempt
@require_POST
def register(request):
    """
    POST /oauth/register/

    RFC 7591 Dynamic Client Registration.
    ChatGPT calls this to register itself before starting the OAuth flow.
    """
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_client_metadata"}, status=400)

    redirect_uris = data.get("redirect_uris", [])
    client_name = data.get("client_name", "Dynamic Client")
    grant_types = data.get("grant_types", ["authorization_code"])
    response_types = data.get("response_types", ["code"])
    token_endpoint_auth_method = data.get("token_endpoint_auth_method", "client_secret_post")

    if not redirect_uris:
        return JsonResponse(
            {"error": "invalid_redirect_uri", "error_description": "redirect_uris is required."},
            status=400,
        )

    if "authorization_code" not in grant_types:
        return JsonResponse(
            {"error": "invalid_client_metadata", "error_description": "Only authorization_code grant is supported."},
            status=400,
        )

    from apps.accounts.models import Account

    try:
        account = Account.objects.get(pk=DEFAULT_REGISTRATION_ACCOUNT_ID)
    except Account.DoesNotExist:
        logger.error("Default registration account %s not found", DEFAULT_REGISTRATION_ACCOUNT_ID)
        return JsonResponse({"error": "server_error"}, status=500)

    # Check if client with same name + redirect_uri already exists
    redirect_uri = redirect_uris[0]
    existing = OAuthApplication.objects.filter(name=client_name, redirect_uri=redirect_uri, is_active=True).first()
    if existing:
        # Return existing credentials (client_secret cannot be recovered, create new)
        # Re-generate secret for the existing app
        _, client_secret, prefix, secret_hash = OAuthApplication.generate_credentials()
        existing.client_secret_hash = secret_hash
        existing.client_secret_prefix = prefix
        existing.save(update_fields=["client_secret_hash", "client_secret_prefix"])

        logger.info("Re-registered existing OAuth app: %s", existing.name)

        return JsonResponse({
            "client_id": existing.client_id,
            "client_secret": client_secret,
            "client_name": existing.name,
            "redirect_uris": [existing.redirect_uri],
            "grant_types": grant_types,
            "response_types": response_types,
            "token_endpoint_auth_method": token_endpoint_auth_method,
            "client_id_issued_at": int(existing.created_at.timestamp()),
            "client_secret_expires_at": 0,
        }, status=200)

    # Create new client
    client_id, client_secret, prefix, secret_hash = OAuthApplication.generate_credentials()
    app = OAuthApplication.objects.create(
        account=account,
        name=client_name,
        client_id=client_id,
        client_secret_hash=secret_hash,
        client_secret_prefix=prefix,
        redirect_uri=redirect_uri,
        mode="safe",
    )

    logger.info("Dynamic client registered: %s (client_id=%s)", app.name, client_id)

    return JsonResponse({
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": app.name,
        "redirect_uris": redirect_uris,
        "grant_types": grant_types,
        "response_types": response_types,
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "client_id_issued_at": int(app.created_at.timestamp()),
        "client_secret_expires_at": 0,
    }, status=201)
