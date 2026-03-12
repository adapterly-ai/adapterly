"""
Context processors for core app.
"""

from django.conf import settings


def app_name(request):
    """
    Add app branding variables to template context from settings.
    """
    return {
        "app_name": settings.APP_NAME,
        "app_logo_url": getattr(settings, "APP_LOGO_URL", ""),
        "app_tagline": getattr(settings, "APP_TAGLINE", ""),
        "app_primary_color": getattr(settings, "APP_PRIMARY_COLOR", "#6366f1"),
        "app_secondary_color": getattr(settings, "APP_SECONDARY_COLOR", "#8b5cf6"),
    }
