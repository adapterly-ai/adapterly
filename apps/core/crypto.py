"""
Encryption utilities for storing sensitive credentials.

Uses Fernet symmetric encryption with a key derived from Django's SECRET_KEY.
"""

import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _get_fernet_key():
    """
    Derive a Fernet-compatible key from Django's SECRET_KEY.
    Fernet requires a 32-byte base64-encoded key.
    """
    # Use SHA256 to get 32 bytes from SECRET_KEY
    key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def _get_fernet():
    """Get Fernet instance with the derived key."""
    return Fernet(_get_fernet_key())


def encrypt_value(value):
    """
    Encrypt a string value.
    Returns base64-encoded encrypted string, or None if value is None/empty.
    """
    if not value:
        return value

    fernet = _get_fernet()
    encrypted = fernet.encrypt(value.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_value(encrypted_value):
    """
    Decrypt an encrypted value.
    Returns decrypted string, or None if value is None/empty.
    """
    if not encrypted_value:
        return encrypted_value

    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted_value.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception:
        # If decryption fails, return the original value
        # (might be an old unencrypted value)
        return encrypted_value
