from django.urls import path

from . import views

app_name = "oauth"

urlpatterns = [
    path("authorize/", views.authorize, name="authorize"),
    path("token/", views.token, name="token"),
]

# Well-known endpoints — included at root level in urls.py
wellknown_urlpatterns = [
    path(
        ".well-known/oauth-authorization-server",
        views.authorization_server_metadata,
        name="oauth-as-metadata",
    ),
    path(
        ".well-known/oauth-protected-resource",
        views.protected_resource_metadata,
        name="oauth-pr-metadata-root",
    ),
    path(
        ".well-known/oauth-protected-resource/<path:resource_path>",
        views.protected_resource_metadata,
        name="oauth-pr-metadata",
    ),
]
