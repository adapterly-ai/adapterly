"""
Account app tests - basic model and signal tests.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Account, AccountUser

User = get_user_model()


class AccountModelTestCase(TestCase):
    """Tests for Account model."""

    def test_create_account(self):
        """Test that an account can be created."""
        account = Account.objects.create(name="Test Account")
        self.assertEqual(account.name, "Test Account")
        self.assertIsNotNone(account.created_at)

    def test_account_str(self):
        """Test account string representation."""
        account = Account.objects.create(name="My Account")
        self.assertEqual(str(account), "My Account")


class AccountUserModelTestCase(TestCase):
    """Tests for AccountUser model."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.account = Account.objects.create(name="Test Account")

    def test_create_account_user(self):
        """Test that an account user can be created."""
        account_user = AccountUser.objects.create(account=self.account, user=self.user, is_admin=True)
        self.assertEqual(account_user.account, self.account)
        self.assertEqual(account_user.user, self.user)
        self.assertTrue(account_user.is_admin)

    def test_account_user_str(self):
        """Test account user string representation."""
        account_user = AccountUser.objects.create(account=self.account, user=self.user, is_admin=False)
        self.assertIn(self.user.username, str(account_user))
        self.assertIn(self.account.name, str(account_user))

    def test_unique_account_user(self):
        """Test that a user can only be added to an account once."""
        AccountUser.objects.create(account=self.account, user=self.user, is_admin=True)
        # Attempting to create a duplicate should raise an error
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            AccountUser.objects.create(account=self.account, user=self.user, is_admin=False)


class AccountSignalTestCase(TestCase):
    """Tests for account creation signals."""

    def test_user_gets_account_on_creation(self):
        """Test that creating a user also creates a personal account."""
        user = User.objects.create_user(username="newuser", email="new@example.com", password="testpass123")

        # User should have an account
        account_users = AccountUser.objects.filter(user=user)
        self.assertEqual(account_users.count(), 1)

        # User should be admin of their personal account
        account_user = account_users.first()
        self.assertTrue(account_user.is_admin)
        self.assertTrue(account_user.is_current_active)
