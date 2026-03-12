from django.urls import path

from apps.core import views

urlpatterns = [
    path("", views.landing_page, name="landing"),
    path("dashboard/", views.index, name="index"),
]
