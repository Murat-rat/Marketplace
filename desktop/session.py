"""The logged-in user, kept in memory only.

The token is never written to disk, so closing the app logs the user out
and nothing on the PC can be stolen to impersonate them later.
"""

import time
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class User:
    id: int
    name: str
    email: str
    role: str
    seller_id: int | None

    @property
    def is_seller(self) -> bool:
        return self.seller_id is not None


class Session:
    # Treat the token as expired a little early so a request never starts
    # with a token that expires mid-flight.
    _SAFETY_SECONDS = 30

    def __init__(self):
        self._token: str | None = None
        self._expires_at = 0.0
        self.user: User | None = None

    def start(self, token: str, expires_in: int, user: dict) -> None:
        self._token = token
        self._expires_at = time.monotonic() + int(expires_in) - self._SAFETY_SECONDS
        self.user = User(
            id=int(user["id"]),
            name=str(user["name"]),
            email=str(user["email"]),
            role=str(user["role"]),
            seller_id=user.get("seller_id"),
        )

    def clear(self) -> None:
        self._token = None
        self._expires_at = 0.0
        self.user = None

    def update_email(self, email: str) -> None:
        if self.user is not None:
            self.user = replace(self.user, email=email)

    @property
    def active(self) -> bool:
        return self._token is not None and time.monotonic() < self._expires_at

    @property
    def token(self) -> str | None:
        return self._token if self.active else None
