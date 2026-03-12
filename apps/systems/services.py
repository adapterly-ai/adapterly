"""
System connection testing services.
"""

import base64
import logging

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

logger = logging.getLogger(__name__)

# Timeout for connection tests (seconds)
CONNECTION_TEST_TIMEOUT = 10


def test_system_connection(account_system) -> tuple[bool, str]:
    """
    Test connection to a system using the configured credentials.

    Args:
        account_system: AccountSystem instance with credentials

    Returns:
        Tuple of (success: bool, message: str)
    """
    system = account_system.system

    # Get the primary interface for this system
    interface = system.interfaces.first()
    if not interface:
        return False, f"No interface configured for {system.display_name}"

    # Build the test URL
    base_url = interface.base_url
    if not base_url:
        # Try to get base_url from system variables
        base_url = system.variables.get("base_url", "")

    if not base_url:
        return False, "No base URL configured for this system"

    # Determine auth type from interface configuration
    auth_config = interface.auth or {}
    auth_type = auth_config.get("type", "none")

    # Build headers based on auth type and AccountSystem credentials
    headers = _build_auth_headers(account_system, auth_type, auth_config)

    # Get test endpoint (use a simple endpoint if configured, otherwise just base URL)
    test_endpoint = auth_config.get("test_endpoint", "")
    test_url = f"{base_url.rstrip('/')}/{test_endpoint.lstrip('/')}" if test_endpoint else base_url

    # Make the test request
    try:
        logger.info("Testing connection to %s (%s)", system.display_name, test_url)

        response = requests.get(test_url, headers=headers, timeout=CONNECTION_TEST_TIMEOUT, allow_redirects=True)

        # Check response status
        if response.status_code == 401:
            return False, "Authentication failed - invalid credentials"
        elif response.status_code == 403:
            return False, "Access denied - insufficient permissions"
        elif response.status_code == 404:
            # 404 might be OK for some APIs if the base URL itself doesn't have content
            # but we successfully authenticated
            if "www-authenticate" not in response.headers.get("", "").lower():
                return True, "Connection successful (endpoint returned 404 but auth OK)"
            return False, "Endpoint not found"
        elif response.status_code >= 500:
            return False, f"Server error: {response.status_code}"
        elif response.status_code >= 400:
            return False, f"Request failed: {response.status_code} - {response.reason}"
        else:
            # 2xx or 3xx - success
            return True, f"Connection successful ({response.status_code})"

    except Timeout:
        return False, f"Connection timed out after {CONNECTION_TEST_TIMEOUT} seconds"
    except RequestsConnectionError as e:
        return False, f"Could not connect to server: {_format_connection_error(e)}"
    except RequestException as e:
        logger.warning("Connection test failed for %s: %s", system.display_name, e)
        return False, f"Connection error: {str(e)}"


def _build_auth_headers(account_system, auth_type: str, auth_config: dict) -> dict:
    """
    Build authentication headers based on auth type and credentials.

    Args:
        account_system: AccountSystem with credentials
        auth_type: Type of authentication (api_key, bearer, basic, oauth, oauth2_password, none)
        auth_config: Additional auth configuration from interface

    Returns:
        Dict of headers
    """
    headers = {
        "User-Agent": "Adapterly/1.0 ConnectionTest",
        "Accept": "application/json",
    }

    if auth_type == "api_key":
        # API key can be in header or query param
        key_name = auth_config.get("key_name", "X-API-Key")
        key_location = auth_config.get("key_location", "header")

        if key_location == "header" and account_system.api_key:
            headers[key_name] = account_system.api_key

    elif auth_type == "bearer":
        # Bearer token authentication
        token = account_system.token or account_system.oauth_token
        if token:
            headers["Authorization"] = f"Bearer {token}"

    elif auth_type == "basic":
        # Basic authentication
        if account_system.username and account_system.password:
            credentials = f"{account_system.username}:{account_system.password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

    elif auth_type == "oauth":
        # OAuth token
        if account_system.oauth_token:
            headers["Authorization"] = f"Bearer {account_system.oauth_token}"

    elif auth_type == "oauth2_password":
        # OAuth 2.0 Password Grant - need to get token using username/password
        token = _get_oauth2_password_token(account_system, auth_config)
        if token:
            headers["Authorization"] = f"Bearer {token}"

    elif auth_type == "session":
        # Session-based authentication (XHR)
        if account_system.session_cookie:
            headers["Cookie"] = account_system.session_cookie
        if account_system.csrf_token:
            csrf_header = auth_config.get("csrf_header", "X-CSRF-Token")
            headers[csrf_header] = account_system.csrf_token

    # Add any custom headers from auth_config
    custom_headers = auth_config.get("headers", {})
    headers.update(custom_headers)

    return headers


def _get_oauth2_password_token(account_system, auth_config: dict) -> str:
    """
    Get OAuth 2.0 token using password grant.

    Args:
        account_system: AccountSystem with username/password
        auth_config: Auth configuration with token_url, grant_type, etc.

    Returns:
        Access token string or empty string on failure
    """
    from datetime import timedelta

    from django.utils import timezone

    # Check if we have a valid cached token
    if account_system.oauth_token and not account_system.is_oauth_expired():
        return account_system.oauth_token

    # Get token URL
    token_url = auth_config.get("token_url")
    if not token_url:
        logger.error("No token_url in auth config for OAuth password grant")
        return ""

    username = account_system.username
    password = account_system.password

    if not username or not password:
        logger.error("No username/password for OAuth password grant")
        return ""

    try:
        logger.info("Getting OAuth token for %s", account_system.system.display_name)

        response = requests.post(
            token_url,
            data={"grant_type": auth_config.get("grant_type", "password"), "username": username, "password": password},
            timeout=30,
        )

        if response.status_code != 200:
            logger.error("OAuth token request failed: %s - %s", response.status_code, response.text)
            return ""

        data = response.json()

        token_field = auth_config.get("token_field", "access_token")
        expires_field = auth_config.get("expires_field", "expires_in")

        token = data.get(token_field)
        if not token:
            logger.error("No %s in OAuth response", token_field)
            return ""

        # Cache the token
        account_system.oauth_token = token
        expires_in = data.get(expires_field, 3600)
        account_system.oauth_expires_at = timezone.now() + timedelta(seconds=expires_in - 300)
        account_system.save(update_fields=["oauth_token", "oauth_expires_at"])

        logger.info("Obtained OAuth token for %s", account_system.system.display_name)
        return token

    except Exception as e:
        logger.error("OAuth token request failed: %s", e)
        return ""


def _format_connection_error(error: RequestsConnectionError) -> str:
    """Format connection error for user display."""
    error_str = str(error)

    if "Name or service not known" in error_str or "getaddrinfo failed" in error_str:
        return "Could not resolve hostname - check the URL"
    elif "Connection refused" in error_str:
        return "Connection refused - server may be down"
    elif "SSL" in error_str or "certificate" in error_str.lower():
        return "SSL/TLS error - certificate issue"
    elif "timed out" in error_str.lower():
        return "Connection timed out"
    else:
        # Return a simplified version
        return error_str[:100] if len(error_str) > 100 else error_str
