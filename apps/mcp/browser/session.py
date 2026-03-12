"""
Browser session management for XHR-based integrations.

Uses Playwright for browser automation to handle:
- Login flows (username/password, OAuth, SAML, etc.)
- Session cookie extraction
- CSRF token handling
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class LoginResult:
    """Result of a browser login attempt."""

    success: bool
    session_cookie: str | None = None
    csrf_token: str | None = None
    expires_at: timezone.datetime | None = None
    error: str | None = None
    cookies: dict[str, str] | None = None


class BrowserSessionManager:
    """
    Manages browser sessions for XHR-based system integrations.

    Handles login flows using Playwright and extracts session cookies.
    """

    def __init__(self):
        self._browser = None
        self._playwright = None

    async def _ensure_browser(self):
        """Ensure browser is initialized."""
        if self._browser is not None:
            return

        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            logger.info("Browser initialized")
        except ImportError:
            raise ImportError(
                "Playwright is required for browser sessions. "
                "Install with: pip install playwright && playwright install chromium"
            )

    async def close(self):
        """Close browser and cleanup."""
        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def login(self, system, interface, account_system) -> LoginResult:
        """
        Perform browser login to get session cookies.

        Args:
            system: System model instance
            interface: Interface model instance
            account_system: AccountSystem model instance

        Returns:
            LoginResult with session info or error
        """
        await self._ensure_browser()

        try:
            # Get login configuration from interface
            browser_config = interface.browser or {}
            login_url = browser_config.get("login_url", interface.base_url)

            # Create new browser context
            context = await self._browser.new_context(
                user_agent=browser_config.get("user_agent"), viewport={"width": 1280, "height": 720}
            )

            page = await context.new_page()

            try:
                # Navigate to login page
                await page.goto(login_url, wait_until="networkidle")

                # Perform login based on authentication steps
                result = await self._execute_login_flow(
                    page=page,
                    system=system,
                    interface=interface,
                    account_system=account_system,
                    browser_config=browser_config,
                )

                if result.success:
                    # Extract cookies
                    cookies = await context.cookies()
                    result.cookies = {c["name"]: c["value"] for c in cookies}

                    # Find session cookie
                    session_cookie_name = browser_config.get("session_cookie_name", "sessionid")
                    for cookie in cookies:
                        if cookie["name"] == session_cookie_name:
                            result.session_cookie = cookie["value"]
                            if cookie.get("expires"):
                                result.expires_at = timezone.datetime.fromtimestamp(
                                    cookie["expires"], tz=timezone.get_current_timezone()
                                )
                            break

                    # Find CSRF token
                    csrf_cookie_name = browser_config.get("csrf_cookie_name", "csrftoken")
                    for cookie in cookies:
                        if cookie["name"] == csrf_cookie_name:
                            result.csrf_token = cookie["value"]
                            break

                    # Set default expiration if not found
                    if not result.expires_at:
                        result.expires_at = timezone.now() + timedelta(hours=1)

                return result

            finally:
                await page.close()
                await context.close()

        except Exception as e:
            logger.error(f"Browser login failed: {e}")
            return LoginResult(success=False, error=str(e))

    async def _execute_login_flow(
        self, page, system, interface, account_system, browser_config: dict[str, Any]
    ) -> LoginResult:
        """
        Execute the login flow using authentication steps.
        """
        from apps.systems.models import AuthenticationStep

        # Get authentication steps
        steps = AuthenticationStep.objects.filter(system=system, is_active=True).order_by("step_order")

        if not steps.exists():
            # Use simple login flow
            return await self._simple_login(page=page, account_system=account_system, browser_config=browser_config)

        # Execute each step
        for step in steps:
            result = await self._execute_auth_step(
                page=page, step=step, account_system=account_system, browser_config=browser_config
            )

            if not result.success:
                return result

        return LoginResult(success=True)

    async def _simple_login(self, page, account_system, browser_config: dict[str, Any]) -> LoginResult:
        """
        Execute a simple username/password login.
        """
        try:
            # Get selectors from config or use defaults
            username_selector = browser_config.get("username_selector", 'input[name="username"], input[type="email"]')
            password_selector = browser_config.get(
                "password_selector", 'input[name="password"], input[type="password"]'
            )
            submit_selector = browser_config.get("submit_selector", 'button[type="submit"], input[type="submit"]')

            # Wait for username field
            await page.wait_for_selector(username_selector, timeout=10000)

            # Fill username
            username = account_system.username
            if username:
                await page.fill(username_selector, username)

            # Fill password
            password = account_system.password  # Decrypted by model
            if password:
                await page.fill(password_selector, password)

            # Submit
            await page.click(submit_selector)

            # Wait for navigation or success indicator
            success_selector = browser_config.get("success_selector")
            if success_selector:
                await page.wait_for_selector(success_selector, timeout=15000)
            else:
                await page.wait_for_load_state("networkidle", timeout=15000)

            return LoginResult(success=True)

        except Exception as e:
            logger.error(f"Simple login failed: {e}")
            return LoginResult(success=False, error=str(e))

    async def _execute_auth_step(self, page, step, account_system, browser_config: dict[str, Any]) -> LoginResult:
        """
        Execute a single authentication step.
        """
        try:
            step_type = step.step_type
            input_fields = step.get_input_fields()

            if step_type == "login":
                # Fill username/login field
                for field in input_fields:
                    selector = field.get("selector")
                    field_type = field.get("type", "text")

                    if field_type == "username":
                        value = account_system.username
                    elif field_type == "email":
                        value = account_system.username  # Often email is username
                    else:
                        continue

                    if selector and value:
                        await page.wait_for_selector(selector, timeout=10000)
                        await page.fill(selector, value)

            elif step_type == "password":
                # Fill password field
                for field in input_fields:
                    selector = field.get("selector")
                    if selector:
                        await page.wait_for_selector(selector, timeout=10000)
                        await page.fill(selector, account_system.password)

            elif step_type == "submit":
                # Click submit button
                selector = input_fields[0].get("selector") if input_fields else 'button[type="submit"]'
                await page.click(selector)
                await page.wait_for_load_state("networkidle", timeout=15000)

            elif step_type == "2fa":
                # 2FA is not supported in automated flow
                return LoginResult(success=False, error="2FA authentication requires manual intervention")

            elif step_type == "oauth":
                # OAuth redirect flow
                # This requires special handling - the session will be captured after redirect
                await page.wait_for_load_state("networkidle", timeout=30000)

            return LoginResult(success=True)

        except Exception as e:
            logger.error(f"Auth step {step.step_name} failed: {e}")
            return LoginResult(success=False, error=f"Step {step.step_name}: {str(e)}")

    async def execute_xhr_request(
        self,
        url: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        session_cookie: str | None = None,
        csrf_token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Execute an XHR request using the browser.

        This is useful for systems that require browser-based requests
        with JavaScript execution.
        """
        await self._ensure_browser()

        context = await self._browser.new_context()

        if session_cookie:
            # Set session cookie
            await context.add_cookies([{"name": "sessionid", "value": session_cookie, "url": url}])

        if csrf_token:
            await context.add_cookies([{"name": "csrftoken", "value": csrf_token, "url": url}])

        page = await context.new_page()

        try:
            # Intercept the request and response
            response_data = {}

            async def handle_response(response):
                if response.url == url:
                    try:
                        response_data["status"] = response.status
                        response_data["body"] = await response.json()
                    except Exception:
                        response_data["body"] = await response.text()

            page.on("response", handle_response)

            # Execute JavaScript to make the request
            js_code = f"""
            async () => {{
                const response = await fetch('{url}', {{
                    method: '{method}',
                    headers: {headers or {}},
                    body: {f"JSON.stringify({data})" if data else "null"},
                    credentials: 'include'
                }});
                return {{
                    status: response.status,
                    data: await response.json()
                }};
            }}
            """

            result = await page.evaluate(js_code)
            return result

        finally:
            await page.close()
            await context.close()
