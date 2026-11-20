"""Application errors that map to safe HTTP responses.

Anything that is NOT an AppError is treated as a bug: it is logged with full
detail to CloudWatch and the client only receives a generic 500 message.
"""


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


class ValidationError(AppError):
    status = 400
    code = "validation_error"


class Unauthorized(AppError):
    status = 401
    code = "unauthorized"


class Forbidden(AppError):
    status = 403
    code = "forbidden"


class NotFound(AppError):
    status = 404
    code = "not_found"


class Conflict(AppError):
    status = 409
    code = "conflict"
