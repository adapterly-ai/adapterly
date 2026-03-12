"""
Custom middleware for security.
"""

from django.core.cache import cache
from django.http import HttpResponse


class LoginRateLimitMiddleware:
    """
    Rate limit login attempts by IP address.
    Blocks IPs that exceed the limit.
    """

    # Settings with defaults
    MAX_ATTEMPTS = 5  # Max failed attempts
    LOCKOUT_TIME = 300  # Lockout time in seconds (5 minutes)
    LOGIN_URLS = ["/auth/login/", "/accounts/login/"]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only check POST requests to login URLs
        if request.method == "POST" and any(request.path.startswith(url) for url in self.LOGIN_URLS):
            ip = self._get_client_ip(request)
            cache_key = f"login_attempts_{ip}"

            # Check if IP is locked out
            attempts = cache.get(cache_key, 0)
            if attempts >= self.MAX_ATTEMPTS:
                return HttpResponse(
                    "Too many login attempts. Please try again later.", status=429, content_type="text/plain"
                )

        response = self.get_response(request)

        # Track failed login attempts (status 200 with form errors or redirect back to login)
        if request.method == "POST" and any(request.path.startswith(url) for url in self.LOGIN_URLS):
            # If still on login page after POST, it was likely a failed attempt
            if response.status_code == 200 or (response.status_code == 302 and "login" in response.get("Location", "")):
                ip = self._get_client_ip(request)
                cache_key = f"login_attempts_{ip}"
                attempts = cache.get(cache_key, 0) + 1
                cache.set(cache_key, attempts, self.LOCKOUT_TIME)
            else:
                # Successful login - clear attempts
                ip = self._get_client_ip(request)
                cache_key = f"login_attempts_{ip}"
                cache.delete(cache_key)

        return response

    def _get_client_ip(self, request):
        """Get client IP, handling proxies."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip
