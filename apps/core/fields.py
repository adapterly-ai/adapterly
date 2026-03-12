"""
Custom Django model fields.
"""

from django.db import models

from .crypto import decrypt_value, encrypt_value


class EncryptedCharField(models.CharField):
    """
    CharField that encrypts data before saving and decrypts when reading.
    """

    description = "An encrypted CharField"

    def deconstruct(self):
        """Return field for migrations - Django needs this for custom fields."""
        name, path, args, kwargs = super().deconstruct()
        # Use our custom field path so migrations reference the right class
        return name, "apps.core.fields.EncryptedCharField", args, kwargs

    def get_prep_value(self, value):
        """Encrypt before saving to database."""
        value = super().get_prep_value(value)
        return encrypt_value(value)

    def from_db_value(self, value, expression, connection):
        """Decrypt when reading from database."""
        return decrypt_value(value)

    def to_python(self, value):
        """Convert to Python value."""
        if isinstance(value, str) and value:
            return decrypt_value(value)
        return value


class EncryptedTextField(models.TextField):
    """
    TextField that encrypts data before saving and decrypts when reading.
    """

    description = "An encrypted TextField"

    def deconstruct(self):
        """Return field for migrations - Django needs this for custom fields."""
        name, path, args, kwargs = super().deconstruct()
        return name, "apps.core.fields.EncryptedTextField", args, kwargs

    def get_prep_value(self, value):
        """Encrypt before saving to database."""
        value = super().get_prep_value(value)
        return encrypt_value(value)

    def from_db_value(self, value, expression, connection):
        """Decrypt when reading from database."""
        return decrypt_value(value)

    def to_python(self, value):
        """Convert to Python value."""
        if isinstance(value, str) and value:
            return decrypt_value(value)
        return value
