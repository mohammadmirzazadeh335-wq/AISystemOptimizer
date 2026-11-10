"""Domain error hierarchy.

Every error carries a stable machine-readable ``code`` and a Persian message that
is safe to show to the end user (no SQL, no stack traces, no secrets).
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all expected application errors."""

    code: str = "app.error"
    default_message: str = "خطای نامشخصی رخ داد."

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None,
                 code: str | None = None) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        if code:
            self.code = code
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(AppError):
    code = "validation.error"
    default_message = "اطلاعات وارد شده معتبر نیست."

    def __init__(self, message: str | None = None, *, field: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.field = field


class NotFoundError(AppError):
    code = "not_found"
    default_message = "رکورد مورد نظر یافت نشد."


class ConflictError(AppError):
    code = "conflict"
    default_message = "این عملیات با وضعیت فعلی سیستم سازگار نیست."


class PermissionDeniedError(AppError):
    code = "permission_denied"
    default_message = "شما مجوز انجام این عملیات را ندارید."

    def __init__(self, permission: str | None = None, message: str | None = None) -> None:
        super().__init__(message or (
            f"شما مجوز انجام این عملیات را ندارید (مجوز لازم: {permission})." if permission else None))
        self.permission = permission


class AuthenticationError(AppError):
    code = "auth.failed"
    default_message = "نام کاربری یا رمز عبور نادرست است."


class AccountLockedError(AuthenticationError):
    code = "auth.locked"
    default_message = "حساب کاربری شما به دلیل تلاش‌های ناموفق موقتاً قفل شده است."

    def __init__(self, locked_until: Any = None, minutes_left: int | None = None) -> None:
        msg = "حساب کاربری شما موقتاً قفل شده است. لطفاً بعداً تلاش کنید."
        if minutes_left is not None and minutes_left > 0:
            msg = f"حساب کاربری شما موقتاً قفل شده است. تلاش مجدد تا {minutes_left} دقیقه دیگر ممکن است."
        super().__init__(msg)
        self.locked_until = locked_until
        self.minutes_left = minutes_left


class AccountInactiveError(AuthenticationError):
    code = "auth.inactive"
    default_message = "این حساب کاربری غیرفعال است. با مدیر سیستم تماس بگیرید."


class PasswordPolicyError(ValidationError):
    code = "auth.password_policy"
    default_message = "رمز عبور انتخاب‌شده با سیاست امنیتی سیستم سازگار نیست."


class SetupRequiredError(AppError):
    code = "setup.required"
    default_message = "راه‌اندازی اولیه سیستم انجام نشده است."


class SetupAlreadyCompletedError(AppError):
    code = "setup.completed"
    default_message = "راه‌اندازی اولیه قبلاً انجام شده است."


class SessionExpiredError(AppError):
    code = "session.expired"
    default_message = "نشست کاربری منقضی شده است. لطفاً دوباره وارد شوید."


class BackupError(AppError):
    code = "backup.failed"
    default_message = "عملیات پشتیبان‌گیری با خطا مواجه شد."


class RestoreError(AppError):
    code = "backup.restore_failed"
    default_message = "بازیابی پایگاه داده با خطا مواجه شد."


class ConfigurationError(AppError):
    code = "config.invalid"
    default_message = "تنظیمات برنامه معتبر نیست."


class UnsupportedOperationError(AppError):
    code = "unsupported"
    default_message = "این عملیات در این نسخه پشتیبانی نمی‌شود."
