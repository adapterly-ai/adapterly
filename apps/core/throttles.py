"""
Custom rate limiting throttles.

Käyttö REST vieweissä:
    from apps.core.throttles import LoginThrottle, AIBuilderThrottle

    class MyView(APIView):
        throttle_classes = [LoginThrottle]

Käyttö Django-näkymissä:
    from apps.core.throttles import ratelimit

    @ratelimit(key='user', rate='10/hour')
    def my_view(request):
        ...
"""

from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse
from rest_framework.throttling import SimpleRateThrottle


def ratelimit(key="ip", rate="10/minute"):
    """
    Simple rate limit decorator for Django views.

    Args:
        key: 'ip' or 'user' - what to use as identifier
        rate: 'X/period' where period is second, minute, hour, day

    Example:
        @ratelimit(key='user', rate='5/minute')
        def my_view(request):
            ...
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            # Parse rate
            num, period = rate.split("/")
            num = int(num)
            period_seconds = {
                "second": 1,
                "minute": 60,
                "hour": 3600,
                "day": 86400,
            }.get(period, 60)

            # Get identifier
            if key == "user" and request.user.is_authenticated:
                ident = f"user_{request.user.pk}"
            else:
                x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
                if x_forwarded_for:
                    ident = f"ip_{x_forwarded_for.split(',')[0].strip()}"
                else:
                    ident = f"ip_{request.META.get('REMOTE_ADDR')}"

            cache_key = f"ratelimit_{view_func.__name__}_{ident}"

            # Check current count
            count = cache.get(cache_key, 0)
            if count >= num:
                return HttpResponse(
                    "Rate limit exceeded. Please try again later.", status=429, content_type="text/plain"
                )

            # Increment count
            cache.set(cache_key, count + 1, period_seconds)

            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


class LoginThrottle(SimpleRateThrottle):
    """
    Rate-limits login attempts by IP address.
    Prevents brute force attacks.
    """

    scope = "login"

    def get_cache_key(self, request, view):
        # Use IP address as key (including unauthenticated users)
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class AIBuilderThrottle(SimpleRateThrottle):
    """
    Rate-limits AI Builder calls per user.
    OpenAI API costs money, so usage is limited.
    """

    scope = "ai_builder"

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class MCPCallThrottle(SimpleRateThrottle):
    """
    Rate limits MCP calls per user.
    Estää resurssien ylikuormituksen.
    """

    scope = "mcp_call"

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class BurstThrottle(SimpleRateThrottle):
    """
    Lyhytaikainen burst-rajoitus.
    Estää nopeat peräkkäiset pyynnöt (esim. 10/second).
    """

    scope = "burst"
    rate = "10/second"

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }
