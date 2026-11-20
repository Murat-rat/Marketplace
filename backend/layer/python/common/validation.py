"""Server-side input validation.

The desktop app also validates, but only for user experience. These checks
are the real ones: never trust anything the client sends.
Lengths match the column sizes in the ERD.
"""

import re
from decimal import Decimal, InvalidOperation

from .errors import ValidationError

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PHONE_RE = re.compile(r"^\+?[0-9]{7,14}$")  # fits VARCHAR(15)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def string(
    body: dict,
    field: str,
    *,
    max_len: int,
    min_len: int = 1,
    required: bool = True,
    pattern: re.Pattern | None = None,
    strip: bool = True,
) -> str | None:
    value = body.get(field)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        if required:
            raise ValidationError(f"'{field}' is required", field)
        return None
    if not isinstance(value, str):
        raise ValidationError(f"'{field}' must be text", field)
    if strip:
        value = value.strip()
    if _CONTROL_RE.search(value):
        raise ValidationError(f"'{field}' contains invalid characters", field)
    if not (min_len <= len(value) <= max_len):
        raise ValidationError(f"'{field}' must be between {min_len} and {max_len} characters", field)
    if pattern is not None and not pattern.fullmatch(value):
        raise ValidationError(f"'{field}' has an invalid format", field)
    return value


def email(body: dict, field: str = "email") -> str:
    return string(body, field, max_len=100, min_len=6, pattern=_EMAIL_RE).lower()


def phone(body: dict, field: str = "phone", required: bool = True) -> str | None:
    value = body.get(field)
    if isinstance(value, str):
        body = {**body, field: re.sub(r"[\s\-()]", "", value)}
    return string(body, field, max_len=15, min_len=7, pattern=_PHONE_RE, required=required)


def new_password(body: dict, field: str = "password") -> str:
    value = body.get(field)
    if not isinstance(value, str):
        raise ValidationError(f"'{field}' is required", field)
    if not (8 <= len(value) <= 128):
        raise ValidationError("Password must be between 8 and 128 characters", field)
    if not (re.search(r"[A-Za-z]", value) and re.search(r"[0-9]", value)):
        raise ValidationError("Password must contain at least one letter and one number", field)
    return value


def any_password(body: dict, field: str = "password") -> str:
    """For login: only checks type/size, never reveals the password policy."""
    value = body.get(field)
    if not isinstance(value, str) or not (1 <= len(value) <= 128):
        raise ValidationError(f"'{field}' is required", field)
    return value


def choice(body: dict, field: str, options: set[str], required: bool = True) -> str | None:
    value = body.get(field)
    if value is None:
        if required:
            raise ValidationError(f"'{field}' is required", field)
        return None
    if value not in options:
        raise ValidationError(f"'{field}' must be one of: {', '.join(sorted(options))}", field)
    return value


def integer(body: dict, field: str, *, min_value: int, max_value: int, required: bool = True) -> int | None:
    value = body.get(field)
    if value is None:
        if required:
            raise ValidationError(f"'{field}' is required", field)
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"'{field}' must be a whole number", field)
    if not (min_value <= value <= max_value):
        raise ValidationError(f"'{field}' must be between {min_value} and {max_value}", field)
    return value


def money(body: dict, field: str, *, max_value: Decimal = Decimal("99999999.99"), required: bool = True) -> Decimal | None:
    """Positive amount with at most 2 decimals; fits DECIMAL(10,2)."""
    value = body.get(field)
    if value is None:
        if required:
            raise ValidationError(f"'{field}' is required", field)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValidationError(f"'{field}' must be a number", field)
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValidationError(f"'{field}' must be a number", field) from None
    if not amount.is_finite() or amount <= 0 or amount > max_value or amount.as_tuple().exponent < -2:
        raise ValidationError(f"'{field}' must be a positive amount with at most 2 decimals", field)
    return amount


def path_id(event: dict, name: str) -> int:
    raw = (event.get("pathParameters") or {}).get(name, "")
    if not raw.isdigit() or len(raw) > 10:
        raise ValidationError(f"Invalid {name}", name)
    return int(raw)
