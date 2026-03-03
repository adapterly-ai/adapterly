"""
Fernet decryption compatible with Django's EncryptedCharField / EncryptedTextField.

Delegates to gateway_core.crypto and initializes the secret key from FastAPI settings.
"""

# Initialize gateway_core.crypto with FastAPI's secret key
from gateway_core.crypto import configure_secret_key, decrypt_value, encrypt_value  # noqa: F401

from .config import get_settings

# Configure on import — settings are cached, so this is safe
configure_secret_key(get_settings().secret_key)
