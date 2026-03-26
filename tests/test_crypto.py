"""Tests for adapterly.crypto – Fernet encrypt/decrypt."""

from __future__ import annotations

import pytest

from adapterly.crypto import configure_secret_key, decrypt_value, encrypt_value


@pytest.fixture(autouse=True)
def _setup_crypto():
    """Ensure the crypto module is configured for every test in this file."""
    configure_secret_key("test-secret-key-for-pytest")
    yield


class TestEncryptDecryptRoundtrip:
    """encrypt_value -> decrypt_value should return the original."""

    def test_simple_string(self):
        original = "my-super-secret-token"
        encrypted = encrypt_value(original)
        assert encrypted is not None
        assert encrypted != original
        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_unicode_string(self):
        original = "salasana-\u00e4\u00f6\u00fc-\U0001f511"
        encrypted = encrypt_value(original)
        assert decrypt_value(encrypted) == original

    def test_long_string(self):
        original = "x" * 10_000
        encrypted = encrypt_value(original)
        assert decrypt_value(encrypted) == original

    def test_json_like_string(self):
        original = '{"api_key": "abc123", "nested": {"deep": true}}'
        encrypted = encrypt_value(original)
        assert decrypt_value(encrypted) == original


class TestNoneHandling:
    """None values should pass through untouched."""

    def test_encrypt_none_returns_none(self):
        assert encrypt_value(None) is None

    def test_decrypt_none_returns_none(self):
        assert decrypt_value(None) is None


class TestEmptyStringHandling:
    """Empty strings are treated as falsy and passed through."""

    def test_encrypt_empty_returns_empty(self):
        result = encrypt_value("")
        # empty string is falsy so encrypt_value returns it as-is
        assert result == ""

    def test_decrypt_empty_returns_empty(self):
        result = decrypt_value("")
        assert result == ""


class TestDecryptInvalidData:
    """Decrypting garbage should return the original string (not crash)."""

    def test_decrypt_plain_text_returns_original(self):
        plain = "not-encrypted-at-all"
        result = decrypt_value(plain)
        # The module returns the original value on decrypt failure
        assert result == plain

    def test_decrypt_random_base64(self):
        import base64
        garbage = base64.urlsafe_b64encode(b"totally_wrong").decode()
        result = decrypt_value(garbage)
        assert result == garbage


class TestDifferentKeys:
    """Encrypting with one key and decrypting with another should fail gracefully."""

    def test_wrong_key_returns_ciphertext(self):
        configure_secret_key("key-alpha")
        encrypted = encrypt_value("secret")
        configure_secret_key("key-beta")
        # decrypt with wrong key returns original encrypted string
        result = decrypt_value(encrypted)
        assert result == encrypted
        # restore original key for other tests
        configure_secret_key("test-secret-key-for-pytest")
