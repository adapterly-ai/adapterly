"""Fernet encryption/decryption for credential storage."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

_secret_key: str | None = None


def configure_secret_key(secret: str) -> None:
    global _secret_key
    _secret_key = secret
    _get_fernet_key.cache_clear()


def _get_secret_key() -> str:
    if _secret_key is None:
        raise RuntimeError("crypto: secret key not configured. Call configure_secret_key() first.")
    return _secret_key


@lru_cache
def _get_fernet_key() -> bytes:
    secret = _get_secret_key()
    key_bytes = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def encrypt_value(value: str | None) -> str | None:
    if not value:
        return value
    fernet = Fernet(_get_fernet_key())
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(encrypted_value: str | None) -> str | None:
    if not encrypted_value:
        return encrypted_value
    try:
        fernet = Fernet(_get_fernet_key())
        return fernet.decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
    except Exception:
        return encrypted_value
