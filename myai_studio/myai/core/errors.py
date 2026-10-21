"""Application error hierarchy.

Every user-visible failure travels as an ``AppError`` carrying a translation
key, a safe technical detail and an optional hint.  The UI never shows raw
stack traces; the full trace is written to the structured log instead.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, user-presentable failures."""

    code = "app.error"
    title_key = "error.title"

    def __init__(
        self,
        message: str,
        *,
        message_key: str | None = None,
        hint_key: str | None = None,
        details: str | None = None,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.message_key = message_key
        self.hint_key = hint_key
        self.details = details
        self.context = context or {}
        self.cause = cause

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "context": self.context,
        }


class ConfigurationError(AppError):
    code = "config.error"


class ValidationError(AppError):
    code = "validation.error"


class NotFoundError(AppError):
    code = "not_found"


class PermissionDeniedError(AppError):
    code = "permission_denied"


class ProviderError(AppError):
    """AI / search / media provider failure."""

    code = "provider.error"


class AuthenticationError(ProviderError):
    code = "provider.auth"


class RateLimitError(ProviderError):
    code = "provider.rate_limit"


class InsufficientCreditError(ProviderError):
    code = "provider.credit"


class NetworkError(ProviderError):
    code = "provider.network"


class CancelledError(AppError):
    code = "cancelled"


class ToolError(AppError):
    code = "tool.error"


class SandboxError(ToolError):
    code = "tool.sandbox"


class DatabaseError(AppError):
    code = "database.error"
