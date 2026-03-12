from django.urls import path

from . import views

app_name = "help"

urlpatterns = [
    # Default routes (redirect to English)
    path("", views.help_index, name="index"),
    # Download routes
    path("<str:lang>/download/", views.download_all, name="download_all"),
    path("<str:lang>/download/<slug:page>/", views.download_page, name="download_page"),
    # Language-specific routes
    path("<str:lang>/", views.help_lang_index, name="lang_index"),
    path("<str:lang>/<slug:page>/", views.help_lang_page, name="lang_page"),
    # Legacy route for backwards compatibility
    path("<slug:page>/", views.help_page, name="page"),
]
