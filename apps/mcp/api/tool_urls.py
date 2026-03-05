from django.urls import path

from . import tool_views

app_name = "tools-api"

urlpatterns = [
    path("", tool_views.list_tools, name="list"),
    path("<str:tool_name>/call", tool_views.call_tool, name="call"),
]
