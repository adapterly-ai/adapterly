from django.contrib import admin

from .models import AuthorizationCode, OAuthApplication


@admin.register(OAuthApplication)
class OAuthApplicationAdmin(admin.ModelAdmin):
    list_display = ["name", "client_id", "account", "mode", "is_active", "created_at"]
    list_filter = ["is_active", "mode"]
    search_fields = ["name", "client_id"]
    readonly_fields = ["client_id", "client_secret_hash", "client_secret_prefix", "created_at"]
    fieldsets = (
        (None, {"fields": ("name", "account", "redirect_uri")}),
        ("Credentials", {"fields": ("client_id", "client_secret_prefix", "client_secret_hash")}),
        ("Token Settings", {"fields": ("profile", "project", "mode", "is_active")}),
        ("Timestamps", {"fields": ("created_at",)}),
    )


@admin.register(AuthorizationCode)
class AuthorizationCodeAdmin(admin.ModelAdmin):
    list_display = ["application", "user", "account", "is_used", "expires_at", "created_at"]
    list_filter = ["is_used"]
    readonly_fields = ["code", "created_at"]
    raw_id_fields = ["user", "account"]
