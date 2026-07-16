"""
Encryption for sensitive settings stored in the database.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography library.
The encryption key comes from the SETTINGS_ENCRYPTION_KEY environment
variable — a 32-byte URL-safe base64 key generated once and stored in
Railway's environment variables (never in the database itself).

If SETTINGS_ENCRYPTION_KEY is not set (e.g. during local development
before you've configured it), values are stored unencrypted and a
warning is logged. This means existing local installs keep working
without any manual migration step.

How to generate a key:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Then set it as SETTINGS_ENCRYPTION_KEY in Railway's Variables tab.
"""

import os
import logging
from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

# Prefix added to encrypted values so we can tell them apart from
# plain-text values that were stored before encryption was enabled.
_PREFIX = "enc:"


def _get_fernet():
    key = os.environ.get("SETTINGS_ENCRYPTION_KEY", "")
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        log.error("SETTINGS_ENCRYPTION_KEY is set but is not a valid Fernet key. "
                  "Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
        return None


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string for storage. Returns the original string
    unmodified if no encryption key is configured."""
    if not plaintext:
        return plaintext
    f = _get_fernet()
    if not f:
        return plaintext  # no key configured — store as-is
    encrypted = f.encrypt(plaintext.encode()).decode()
    return _PREFIX + encrypted


def decrypt_value(stored: str) -> str:
    """Decrypt a stored value. Handles three cases:
    1. Value is encrypted (starts with enc:) — decrypt it.
    2. Value is plain text from before encryption was enabled — return as-is.
    3. Decryption fails (wrong key, corrupted) — return empty string and log.
    """
    if not stored or not stored.startswith(_PREFIX):
        return stored  # plain text (pre-encryption or no key configured)
    f = _get_fernet()
    if not f:
        log.warning("Encrypted value found in database but SETTINGS_ENCRYPTION_KEY "
                    "is not set — cannot decrypt. Set the key in your environment.")
        return ""
    try:
        return f.decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        log.error("Failed to decrypt settings value — wrong key or corrupted data.")
        return ""
