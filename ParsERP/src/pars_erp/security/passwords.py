"""Password hashing (Argon2id) and password policy enforcement.

* only Argon2id hashes are stored - plaintext passwords never touch the database
  or the logs;
* hashes are verified with :mod:`argon2`'s constant-time verification;
* parameters are explicit and versioned so they can be raised over time; the
  service layer re-hashes transparently on the next successful login.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from pars_erp.core.errors import PasswordPolicyError, ValidationError
from pars_erp.core.digits import to_latin_digits

# OWASP-recommended baseline for Argon2id (19 MiB x 2 iterations is the minimum;
# we use a stronger desktop-friendly profile).
DEFAULT_TIME_COST = 3
DEFAULT_MEMORY_COST_KIB = 64 * 1024  # 64 MiB
DEFAULT_PARALLELISM = 4
DEFAULT_HASH_LEN = 32
DEFAULT_SALT_LEN = 16


class Argon2PasswordHasher:
    """Thin, explicit wrapper around :class:`argon2.PasswordHasher`."""

    def __init__(self, *, time_cost: int = DEFAULT_TIME_COST,
                 memory_cost: int = DEFAULT_MEMORY_COST_KIB,
                 parallelism: int = DEFAULT_PARALLELISM,
                 hash_len: int = DEFAULT_HASH_LEN,
                 salt_len: int = DEFAULT_SALT_LEN) -> None:
        self._params = {
            "time_cost": time_cost,
            "memory_cost": memory_cost,
            "parallelism": parallelism,
            "hash_len": hash_len,
            "salt_len": salt_len,
        }
        self._hasher = PasswordHasher(type=Type.ID, **self._params)

    @property
    def params(self) -> dict[str, int]:
        return dict(self._params)

    def hash(self, password: str) -> str:
        if not isinstance(password, str) or not password:
            raise ValidationError("رمز عبور نمی‌تواند خالی باشد.", field="password")
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """Constant-time verification; never raises for a wrong password."""
        if not password_hash or not password:
            return False
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except (InvalidHashError, VerificationError):
            return True


# A short, curated list of passwords that appear in every credential-stuffing
# list. It is a *minimum* bar, not a substitution for the length rule.
_COMMON_PASSWORDS = {
    "password", "password1", "passw0rd", "1234567890", "12345678", "123456789",
    "qwerty123", "admin123", "administrator", "welcome1", "letmein", "iloveyou",
    "pars1234", "sep1dar", "sepidar123", "test1234", "changeme", "1qaz2wsx",
    "12345678910", "accounting", "hesabdar", "مدیر1234", "adminadmin",
}


@dataclass(frozen=True)
class PasswordPolicy:
    min_length: int = 10
    max_length: int = 128
    require_letters: bool = True
    require_digits: bool = True
    forbid_username: bool = True
    forbid_common: bool = True

    def describe_fa(self) -> str:
        parts = [f"حداقل {self.min_length} نویسه"]
        if self.require_letters:
            parts.append("شامل حرف")
        if self.require_digits:
            parts.append("شامل رقم")
        if self.forbid_username:
            parts.append("متفاوت از نام کاربری")
        return "؛ ".join(parts)


def _normalize(password: str) -> str:
    return unicodedata.normalize("NFKC", to_latin_digits(password or ""))


def validate_password(password: str, policy: PasswordPolicy | None = None, *,
                      username: str | None = None, full_name: str | None = None) -> None:
    """Raise :class:`PasswordPolicyError` with a Persian explanation."""
    policy = policy or PasswordPolicy()
    value = password or ""
    if not value:
        raise PasswordPolicyError("رمز عبور را وارد کنید.", field="password")
    if len(value) < policy.min_length:
        raise PasswordPolicyError(
            f"رمز عبور باید حداقل {policy.min_length} نویسه باشد.", field="password")
    if len(value) > policy.max_length:
        raise PasswordPolicyError(
            f"رمز عبور نباید بیشتر از {policy.max_length} نویسه باشد.", field="password")
    if value.strip() != value:
        raise PasswordPolicyError("رمز عبور نباید با فاصله شروع یا پایان یابد.", field="password")
    if policy.require_letters and not re.search(r"[^\W\d_]", value, re.UNICODE):
        raise PasswordPolicyError("رمز عبور باید حداقل یک حرف داشته باشد.", field="password")
    if policy.require_digits and not re.search(r"\d", value):
        raise PasswordPolicyError("رمز عبور باید حداقل یک رقم داشته باشد.", field="password")
    lowered = _normalize(value).lower()
    if policy.forbid_common and lowered in _COMMON_PASSWORDS:
        raise PasswordPolicyError("این رمز عبور بسیار رایج است؛ رمز دیگری انتخاب کنید.", field="password")
    if policy.forbid_username and username:
        uname = _normalize(username).strip().lower()
        if uname and (lowered == uname or (len(uname) >= 4 and uname in lowered)):
            raise PasswordPolicyError("رمز عبور نباید شامل نام کاربری باشد.", field="password")
    if full_name:
        for token in _normalize(full_name).split():
            token = token.strip().lower()
            if len(token) >= 4 and token in lowered:
                raise PasswordPolicyError("رمز عبور نباید شامل نام و نام خانوادگی باشد.", field="password")
    if len(set(value)) < 4:
        raise PasswordPolicyError("رمز عبور باید از نویسه‌های متنوع‌تری تشکیل شود.", field="password")


def password_strength(password: str) -> tuple[int, str]:
    """Return ``(score 0-4, Persian label)`` for UI hints (never stored)."""
    value = password or ""
    if not value:
        return 0, "خالی"
    score = 0
    if len(value) >= 10:
        score += 1
    if len(value) >= 14:
        score += 1
    if re.search(r"[^\W\d_]", value, re.UNICODE) and re.search(r"\d", value):
        score += 1
    if re.search(r"[^\w\s]", value, re.UNICODE) or (re.search(r"[A-Z]", value) and re.search(r"[a-z]", value)):
        score += 1
    score = min(score, 4)
    labels = {0: "بسیار ضعیف", 1: "ضعیف", 2: "متوسط", 3: "قوی", 4: "بسیار قوی"}
    return score, labels[score]
