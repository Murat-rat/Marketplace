"""Client-side checks, only for a nicer experience (instant feedback).

The server repeats every check; these rules mirror backend/layer/python/common/validation.py.
Each function returns an error message, or None when the value is fine.
"""

import re

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PHONE_RE = re.compile(r"^\+?[0-9]{7,14}$")


def name(value: str) -> str | None:
    if not 2 <= len(value.strip()) <= 80:
        return "Name must be between 2 and 80 characters."
    return None


def email(value: str) -> str | None:
    value = value.strip()
    if not value:
        return "Email is required."
    if len(value) > 100 or not _EMAIL_RE.fullmatch(value):
        return "Enter a valid email address."
    return None


def phone(value: str) -> str | None:
    cleaned = re.sub(r"[\s\-()]", "", value)
    if cleaned and not _PHONE_RE.fullmatch(cleaned):
        return "Phone must have 7 to 14 digits (an optional + at the start)."
    return None


def password(value: str) -> str | None:
    if not 8 <= len(value) <= 128:
        return "Password must be between 8 and 128 characters."
    if not (re.search(r"[A-Za-z]", value) and re.search(r"[0-9]", value)):
        return "Password must contain at least one letter and one number."
    return None


def store_name(value: str) -> str | None:
    if not 2 <= len(value.strip()) <= 60:
        return "Store name must be between 2 and 60 characters."
    return None


def store_description(value: str) -> str | None:
    if len(value.strip()) > 2000:
        return "Store description can be at most 2000 characters."
    return None
