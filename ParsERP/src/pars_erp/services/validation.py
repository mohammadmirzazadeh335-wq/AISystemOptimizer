"""Reusable field validators (Persian messages, single source of truth)."""

from __future__ import annotations

import re

from pars_erp.core.digits import normalize_text, normalize_username, to_latin_digits
from pars_erp.core.errors import ValidationError

USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,32}$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_PHONE_PATTERN = re.compile(r"^[0-9+\-\s()]{4,20}$")


def validate_username(value: str | None) -> str:
    username = normalize_username(value)
    if not username:
        raise ValidationError("نام کاربری را وارد کنید.", field="username")
    if not USERNAME_PATTERN.match(username):
        raise ValidationError(
            "نام کاربری باید ۳ تا ۳۲ نویسه و شامل حروف انگلیسی کوچک، ارقام، نقطه، خط تیره یا زیرخط باشد.",
            field="username")
    return username


def validate_full_name(value: str | None) -> str:
    name = normalize_text(value)
    if not name:
        raise ValidationError("نام و نام خانوادگی را وارد کنید.", field="full_name")
    if len(name) < 3:
        raise ValidationError("نام و نام خانوادگی باید حداقل ۳ نویسه باشد.", field="full_name")
    if len(name) > 160:
        raise ValidationError("نام و نام خانوادگی نباید بیشتر از ۱۶۰ نویسه باشد.", field="full_name")
    return name


def validate_email(value: str | None) -> str | None:
    email = normalize_text(value).lower()
    if not email:
        return None
    if not _EMAIL_PATTERN.match(email):
        raise ValidationError("قالب ایمیل معتبر نیست.", field="email")
    if len(email) > 160:
        raise ValidationError("ایمیل نباید بیشتر از ۱۶۰ نویسه باشد.", field="email")
    return email


def validate_phone(value: str | None) -> str | None:
    phone = normalize_text(to_latin_digits(value))
    if not phone:
        return None
    if not _PHONE_PATTERN.match(phone):
        raise ValidationError("شماره تلفن معتبر نیست.", field="phone")
    return phone


def validate_notes(value: str | None, *, max_length: int = 1000) -> str | None:
    notes = normalize_text(value)
    if not notes:
        return None
    if len(notes) > max_length:
        raise ValidationError(f"توضیحات نباید بیشتر از {max_length} نویسه باشد.", field="notes")
    return notes


def validate_required_text(value: str | None, *, field: str, label: str,
                           min_length: int = 1, max_length: int = 200) -> str:
    text = normalize_text(value)
    if not text:
        raise ValidationError(f"{label} را وارد کنید.", field=field)
    if len(text) < min_length:
        raise ValidationError(f"{label} باید حداقل {min_length} نویسه باشد.", field=field)
    if len(text) > max_length:
        raise ValidationError(f"{label} نباید بیشتر از {max_length} نویسه باشد.", field=field)
    return text
