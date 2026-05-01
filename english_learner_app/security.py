from __future__ import annotations

import hashlib
import hmac
import secrets


PASSWORD_ITERATIONS = 210_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"{PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_value: str) -> bool:
    try:
        iterations_text, salt_hex, digest_hex = stored_value.split("$", 2)
        iterations = int(iterations_text)
    except (ValueError, TypeError):
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations,
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def make_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"

