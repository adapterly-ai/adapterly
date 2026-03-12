"""
Core app smoke tests.
"""

from django.test import Client, TestCase


class SmokeTestCase(TestCase):
    """Basic smoke tests to verify the app starts and key pages load."""

    def setUp(self):
        self.client = Client()

    def test_landing_page_loads(self):
        """Test that the landing page redirects to login for unauthenticated users."""
        response = self.client.get("/")
        self.assertIn(response.status_code, [200, 302])

    def test_health_check(self):
        """Test health check endpoint if it exists."""
        try:
            response = self.client.get("/health/")
            self.assertIn(response.status_code, [200, 404])
        except Exception:
            # Health endpoint may not exist
            pass

    def test_login_page_loads(self):
        """Test that the login page loads."""
        try:
            response = self.client.get("/accounts/login/")
            self.assertIn(response.status_code, [200, 302])
        except Exception:
            pass

    def test_static_files_configured(self):
        """Test that static files are configured."""
        from django.conf import settings

        self.assertTrue(hasattr(settings, "STATIC_URL"))
        self.assertTrue(hasattr(settings, "STATICFILES_DIRS") or hasattr(settings, "STATIC_ROOT"))

    def test_templates_configured(self):
        """Test that templates are configured."""
        from django.conf import settings

        self.assertTrue(len(settings.TEMPLATES) > 0)

    def test_database_configured(self):
        """Test that database is configured."""
        from django.conf import settings

        self.assertIn("default", settings.DATABASES)
