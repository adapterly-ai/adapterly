from django.urls import path

from . import views

urlpatterns = [
    path("", views.account_dashboard, name="account_dashboard"),
    path("profile/", views.user_profile, name="user_profile"),
    path("welcome/", views.account_welcome, name="account_welcome"),
    path("switch/", views.switch_account, name="switch_account"),
    path("switch/ajax/", views.switch_account_ajax, name="switch_account_ajax"),
    path("settings/", views.account_settings, name="account_settings"),
    path("change-name/", views.change_account_name, name="change_account_name"),
    path("change-password/", views.change_password, name="change_password"),
    path("remove-user/", views.remove_user_from_account, name="remove_user_from_account"),
    path("toggle-admin/", views.toggle_admin_status, name="toggle_admin_status"),
    path("invite/", views.invite_user, name="invite_user"),
    path("invite/<uuid:token>/", views.accept_invitation, name="accept_invitation"),
    path("create/", views.create_account, name="create_account"),
    path("api-token/", views.api_token, name="api_token"),
    path("authorize/<str:user_code>/", views.device_authorize, name="device_authorize"),
]
