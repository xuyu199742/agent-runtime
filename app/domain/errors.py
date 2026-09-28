class AppError(Exception):
    code = "INTERNAL_ERROR"


class NotFound(AppError):
    code = "VALIDATION_ERROR"


class Conflict(AppError):
    code = "VALIDATION_ERROR"


class InvalidConfiguration(AppError):
    code = "VALIDATION_ERROR"
