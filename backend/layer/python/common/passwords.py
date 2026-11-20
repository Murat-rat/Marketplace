"""Password hashing with scrypt from the Python standard library.

Stored format (fits in credentials.password_hash VARCHAR(255)):

    scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>

Parameters are stored with each hash so they can be raised later without
breaking existing accounts. No compiled dependency is needed on Lambda.
"""

import base64
import hashlib
import hmac
import secrets

_N = 2**14
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16
_MAXMEM = 64 * 1024 * 1024


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected), maxmem=_MAXMEM
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# Used when the email does not exist, so a failed login takes the same time
# whether or not the account exists (prevents user enumeration by timing).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def burn_time(password: str) -> None:
    verify_password(password, _DUMMY_HASH)
