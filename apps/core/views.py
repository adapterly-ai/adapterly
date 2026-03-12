from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def landing_page(request):
    """Redirect to login page."""
    return redirect("account_login")


@login_required
def index(request):
    return redirect("projects:list")
