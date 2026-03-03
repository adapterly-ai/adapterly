"""
Fernet encryption/decryption - no Django dependency.

Derives Fernet key from a secret string (compatible with Django's EncryptedCharField).
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

_secret_key: str | None = None


def configure_secret_key(secret: str) -> None:
    """Set the secret key used for Fernet encryption. Must be called at startup."""
    global _secret_key
    _secret_key = secret
    # Clear cached Fernet key so it's re-derived
    _get_fernet_key.cache_clear()


def _get_secret_key() -> str:
    """Get the configured secret key."""
    if _secret_key is None:
        raise RuntimeError("gateway_core.crypto: secret key not configured. Call configure_secret_key() first.")
    return _secret_key


@lru_cache
def _get_fernet_key() -> bytes:
    """Derive Fernet key from secret (same algorithm as Django's apps/core/crypto.py)."""
    secret = _get_secret_key()
    key_bytes = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def encrypt_value(value: str | None) -> str | None:
    """Encrypt a string value with Fernet. Compatible with Django's EncryptedCharField."""
    if not value:
        return value
    fernet = Fernet(_get_fernet_key())
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(encrypted_value: str | None) -> str | None:
    """
    Decrypt a Fernet-encrypted value.
    Returns original string on failure (may be an old unencrypted value).
    """
    if not encrypted_value:
        return encrypted_value
    try:
        fernet = Fernet(_get_fernet_key())
        return fernet.decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
    except Exception:
        return encrypted_value
