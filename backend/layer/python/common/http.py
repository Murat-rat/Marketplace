"""Request parsing, JSON responses and routing for API Gateway HTTP APIs (payload v2.0)."""

import base64
import datetime as dt
import json
import logging
from decimal import Decimal
from typing import Callable

from .errors import AppError, NotFound, ValidationError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_BODY_BYTES = 64 * 1024


def _default(value):
    if isinstance(value, Decimal):
        return str(value)  # keep money exact; the client converts it
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    raise TypeError(f"Not JSON serialisable: {type(value).__name__}")


def json_response(status: int, body: dict | list) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
        "body": json.dumps(body, default=_default),
    }


def parse_body(event: dict, allowed: set[str]) -> dict:
    """Parse a JSON object body and reject unknown fields.

    Rejecting unknown fields blocks mass-assignment attempts such as sending
    "role": "admin", "price": 0.01 or "user_id": 7 alongside normal fields.
    """
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise ValidationError("Request body must be JSON") from None
    if len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        raise ValidationError("Request body is too large")
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise ValidationError("Request body must be JSON") from None
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object")
    unknown = set(body) - allowed
    if unknown:
        raise ValidationError(f"Unexpected field(s): {', '.join(sorted(unknown))}")
    return body


def parse_query(event: dict, allowed: set[str], max_len: int = 200) -> dict[str, str]:
    """Return the query string as {name: value}, rejecting unknown or oversized parameters."""
    params = event.get("queryStringParameters") or {}
    unknown = set(params) - allowed
    if unknown:
        raise ValidationError(f"Unexpected parameter(s): {', '.join(sorted(unknown))}")
    for name, value in params.items():
        if len(value) > max_len:
            raise ValidationError(f"'{name}' is too long", name)
    return dict(params)


def query_int(params: dict, name: str, *, default: int | None, min_value: int, max_value: int) -> int | None:
    raw = params.get(name)
    if raw is None or raw == "":
        return default
    if not raw.isdigit() or len(raw) > 10:
        raise ValidationError(f"'{name}' must be a whole number", name)
    value = int(raw)
    if not (min_value <= value <= max_value):
        raise ValidationError(f"'{name}' must be between {min_value} and {max_value}", name)
    return value


Route = Callable[[dict], tuple[int, dict | list]]


def make_handler(routes: dict[str, Route]):
    """Build a lambda_handler that dispatches on routeKey (e.g. 'POST /login').

    Expected errors (AppError) become clean 4xx responses. Anything else is
    logged in CloudWatch and returned as a generic 500 with no internal detail.
    Request bodies are never logged (they may contain passwords or card data).
    """

    def lambda_handler(event, context):
        route_key = event.get("routeKey", "")
        request_id = getattr(context, "aws_request_id", "-")
        route = routes.get(route_key)
        try:
            if route is None:
                raise NotFound("Route not found")
            status, payload = route(event)
        except AppError as err:
            status = err.status
            payload = {"error": err.code, "message": err.message}
            if err.field:
                payload["field"] = err.field
        except Exception:
            logger.exception("Unhandled error on %s (request %s)", route_key, request_id)
            status, payload = 500, {"error": "internal_error", "message": "Something went wrong. Try again later."}
        logger.info("%s -> %s (request %s)", route_key, status, request_id)
        return json_response(status, payload)

    return lambda_handler
