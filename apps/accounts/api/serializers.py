from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.accounts.models import Account, AccountUser

User = get_user_model()


class AccountSerializer(serializers.ModelSerializer):
    """
    Serializer for the Account model.
    """

    user_count = serializers.SerializerMethodField()
    admin_count = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = ["id", "name", "created_at", "user_count", "admin_count"]
        read_only_fields = ["id", "created_at"]

    def get_user_count(self, obj):
        """Count the number of users in the account."""
        return obj.accountuser_set.count()

    def get_admin_count(self, obj):
        """Count the number of admin users in the account."""
        return obj.accountuser_set.filter(is_admin=True).count()


class AccountUserSerializer(serializers.ModelSerializer):
    """
    Serializer for the AccountUser model.
    """

    account_name = serializers.CharField(source="account.name", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.get_full_name", read_only=True)

    class Meta:
        model = AccountUser
        fields = ["id", "account", "account_name", "user", "username", "email", "full_name", "is_admin", "created_at"]
        read_only_fields = ["id", "created_at"]


class CreateAccountUserSerializer(serializers.Serializer):
    """
    Serializer for creating a new AccountUser.
    """

    account_id = serializers.IntegerField()
    user_id = serializers.IntegerField()
    is_admin = serializers.BooleanField(default=False)

    def validate_account_id(self, value):
        """Validate that the account exists."""
        try:
            Account.objects.get(id=value)
            return value
        except Account.DoesNotExist:
            raise serializers.ValidationError("Account not found.")

    def validate_user_id(self, value):
        """Validate that the user exists."""
        try:
            User.objects.get(id=value)
            return value
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")

    def validate(self, data):
        """Validate that the user is not already in the account."""
        account_id = data.get("account_id")
        user_id = data.get("user_id")

        if AccountUser.objects.filter(account_id=account_id, user_id=user_id).exists():
            raise serializers.ValidationError("User is already a member of this account.")

        return data
