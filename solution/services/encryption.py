
import os
import base64
import hashlib
import hmac

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

load_dotenv()

def get_encryption_key() -> bytes:
    """Load a 32-byte AES encryption key from environment."""

    key = os.getenv("PII_ENCRYPTION_KEY")

    if not key:
        raise RuntimeError("PII_ENCRYPTION_KEY is not configured")

    decoded = base64.b64decode(key, validate=True)

    if len(decoded) != 32:
        raise ValueError("Encryption key must be 32 bytes")

    return decoded


def get_hmac_key() -> bytes:
    """Load a separate HMAC key from environment."""

    key = os.getenv("PII_HMAC_KEY")

    if not key:
        raise RuntimeError("PII_HMAC_KEY is not configured")

    decoded = base64.b64decode(key, validate=True)

    if len(decoded) < 32:
        raise ValueError("HMAC key must be at least 32 bytes")

    return decoded


def encrypt_pii(value: str) -> str:
    """Encrypt PII using AES-256-GCM."""

    if not value:
        raise ValueError("Cannot encrypt empty PII")

    key = get_encryption_key()

    aes = AESGCM(key)

    nonce = os.urandom(12)

    encrypted = aes.encrypt(
        nonce,
        value.encode("utf-8"),
        None
    )

    # Store nonce and ciphertext together.
    combined = nonce + encrypted

    return base64.b64encode(combined).decode("utf-8")


def decrypt_pii(encrypted_value: str) -> str:
    """Decrypt AES-256-GCM encrypted PII."""

    key = get_encryption_key()

    combined = base64.b64decode(encrypted_value)

    nonce = combined[:12]
    ciphertext = combined[12:]

    aes = AESGCM(key)

    decrypted = aes.decrypt(
        nonce,
        ciphertext,
        None
    )

    return decrypted.decode("utf-8")


def phone_fingerprint(phone: str) -> str:
    """
    Generate deterministic HMAC fingerprint for phone matching.

    The phone must already be normalized.
    """

    if not phone:
        raise ValueError("Phone cannot be empty")

    key = get_hmac_key()

    return hmac.new(
        key,
        phone.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
