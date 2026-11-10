"""Password hashing and field-level encryption for customer records."""

import hashlib
import hmac
import os
from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet, InvalidToken


AUTH_ITERATIONS = 200_000
ENCRYPTION_PREFIX = "enc:v1:"
ENCRYPTED_FIELDS = {
    "owner_name",
    "external_id",
    "address",
    "note",
    "visit_log",
    "name",
    "birth_year",
}
DECRYPTION_ERROR_TEXT = "無法解密"


def hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        AUTH_ITERATIONS,
    )
    return salt.hex(), digest.hex()


def verify_password(password, salt_hex, digest_hex):
    salt = bytes.fromhex(salt_hex)
    _salt, candidate_hex = hash_password(password, salt)
    return hmac.compare_digest(candidate_hex, digest_hex)


def derive_encryption_key(password, salt_hex):
    salt = bytes.fromhex(salt_hex)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        AUTH_ITERATIONS,
        dklen=32,
    )
    return urlsafe_b64encode(key)


def make_fernet(encryption_key):
    return Fernet(encryption_key)


def encrypt_value(fernet, value):
    if value in (None, ""):
        return value
    text = str(value)
    if text.startswith(ENCRYPTION_PREFIX):
        return text
    token = fernet.encrypt(text.encode("utf-8")).decode("ascii")
    return ENCRYPTION_PREFIX + token


def decrypt_value(fernet, value):
    if value in (None, ""):
        return value
    text = str(value)
    if not text.startswith(ENCRYPTION_PREFIX):
        return text
    token = text[len(ENCRYPTION_PREFIX) :]
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return DECRYPTION_ERROR_TEXT


def encrypt_record(fernet, data):
    encrypted = dict(data)
    for key in ENCRYPTED_FIELDS:
        if key in encrypted:
            encrypted[key] = encrypt_value(fernet, encrypted[key])
    return encrypted
