"""JWT issuing and verification (HS256).

The token is the ONLY source of truth for who is calling. Lambdas must take
user_id / role / seller_id from the Principal returned by require_auth(),
never from the request body or query string.

Environment:
    JWT_SECRET       at least 32 characters, random
    JWT_TTL_SECONDS  optional, default 3600
"""

import os
import time
from dataclasses import dataclass

import jwt

from .errors import Forbidden, Unauthorized

_ALGORITHM = "HS256"
_ISSUER = "marketplace-api"


@dataclass(frozen=True)
class Principal:
    user_id: int
    role: str               # users.role from the database: 'buyer' or 'admin'
    seller_id: int | None   # set only if the user has an active seller profile

    @property
    def is_seller(self) -> bool:
        return self.seller_id is not None


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET is missing or shorter than 32 characters")
    return secret


def issue_token(user_id: int, role: str, seller_id: int | None) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    ttl = int(os.environ.get("JWT_TTL_SECONDS", "3600"))
    now = int(time.time())
    claims = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + ttl,
        "iss": _ISSUER,
    }
    if seller_id is not None:
        claims["sid"] = seller_id
    return jwt.encode(claims, _secret(), algorithm=_ALGORITHM), ttl


def require_auth(event: dict, role: str | None = None, seller: bool = False) -> Principal:
    """Validate the Bearer token of an API Gateway event and return the caller.

    role="admin"  -> only users whose users.role is admin
    seller=True   -> only users with an active seller profile
    """
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Missing or invalid authorization token")

    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[_ALGORITHM],  # pinned: rejects "alg": "none" and algorithm switching
            issuer=_ISSUER,
            options={"require": ["sub", "role", "exp", "iat", "iss"]},
        )
        principal = Principal(
            user_id=int(claims["sub"]),
            role=str(claims["role"]),
            seller_id=int(claims["sid"]) if "sid" in claims else None,
        )
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise Unauthorized("Missing or invalid authorization token") from None

    if role is not None and principal.role != role:
        raise Forbidden("You do not have permission to do this")
    if seller and not principal.is_seller:
        raise Forbidden("Only sellers can do this")
    return principal
