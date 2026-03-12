"""Tests for gateway_core.crypto — Fernet encrypt/decrypt."""

import pytest

from gateway_core import crypto
from gateway_core.crypto import configure_secret_key, decrypt_value, encrypt_value


class TestEncryptDecryptRoundTrip:
    def test_round_trip(self):
        plaintext = "hello world"
        encrypted = encrypt_value(plaintext)
        assert encrypted is not None
        assert encrypted != plaintext
        assert decrypt_value(encrypted) == plaintext

    def test_round_trip_unicode(self):
        plaintext = "mökki äö 🏠"
        encrypted = encrypt_value(plaintext)
        assert decrypt_value(encrypted) == plaintext

    def test_none_passthrough(self):
        assert encrypt_value(None) is None
        assert decrypt_value(None) is None

    def test_empty_string_passthrough(self):
        assert encrypt_value("") == ""
        assert decrypt_value("") == ""

    def test_different_key_cannot_decrypt(self):
        plaintext = "secret data"
        encrypted = encrypt_value(plaintext)

        configure_secret_key("different-key-entirely")
        # With wrong key, decrypt_value returns the ciphertext as-is (fallback)
        result = decrypt_value(encrypted)
        assert result == encrypted  # falls back to original encrypted string

        # Restore for other tests
        configure_secret_key("test-secret-key-for-unit-tests")

    def test_no_secret_key_raises(self):
        crypto._secret_key = None
        crypto._get_fernet_key.cache_clear()

        with pytest.raises(RuntimeError, match="secret key not configured"):
            encrypt_value("test")

        # Restore
        configure_secret_key("test-secret-key-for-unit-tests")
