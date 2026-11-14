"""Argon2id hashing and the password policy."""

from __future__ import annotations

import pytest

from pars_erp.core.errors import PasswordPolicyError
from pars_erp.security.passwords import (
    Argon2PasswordHasher,
    PasswordPolicy,
    password_strength,
    validate_password,
)


def test_production_parameters_are_argon2id() -> None:
    hasher = Argon2PasswordHasher()
    params = hasher.params
    assert params["time_cost"] >= 2
    assert params["memory_cost"] >= 19 * 1024          # OWASP minimum for Argon2id
    assert params["parallelism"] >= 1
    digest = hasher.hash("CorrectHorse123")
    assert digest.startswith("$argon2id$")
    assert "CorrectHorse123" not in digest


def test_hash_is_salted_and_never_reused(fast_hasher: Argon2PasswordHasher) -> None:
    first = fast_hasher.hash("SamePassword123")
    second = fast_hasher.hash("SamePassword123")
    assert first != second
    assert fast_hasher.verify(first, "SamePassword123")
    assert fast_hasher.verify(second, "SamePassword123")


def test_verify_rejects_wrong_and_malformed(fast_hasher: Argon2PasswordHasher) -> None:
    digest = fast_hasher.hash("RightPassword123")
    assert fast_hasher.verify(digest, "WrongPassword123") is False
    assert fast_hasher.verify("not-a-hash", "RightPassword123") is False
    assert fast_hasher.verify(digest, "") is False


def test_needs_rehash_detects_weaker_parameters() -> None:
    weak = Argon2PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1, hash_len=16)
    strong = Argon2PasswordHasher()
    digest = weak.hash("SomePassword123")
    assert strong.needs_rehash(digest) is True
    assert strong.needs_rehash(strong.hash("SomePassword123")) is False


@pytest.mark.parametrize("password", ["short1", "abcdefghij", "1234567890", "adminpassword1"])
def test_policy_rejects_weak_passwords(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password(password, PasswordPolicy(), username="admin")


def test_policy_rejects_username_and_name_inside_password() -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password("mohammad12345", PasswordPolicy(), username="mohammad")
    with pytest.raises(PasswordPolicyError):
        validate_password("rezapass1234", PasswordPolicy(), full_name="Reza Rezaei")
    with pytest.raises(PasswordPolicyError):
        validate_password("password", PasswordPolicy())
    with pytest.raises(PasswordPolicyError):
        validate_password("MyHesabdar1", PasswordPolicy(), username="hesabdar")


def test_policy_accepts_reasonable_password() -> None:
    validate_password("Sandogh_1404!", PasswordPolicy(min_length=10), username="hesabdar")
    validate_password("۱۲۳۴۵۶۷۸۹۰ab", PasswordPolicy(min_length=10))  # Persian digits count


def test_policy_length_bounds() -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password("a1" * 80, PasswordPolicy(max_length=64))
    with pytest.raises(PasswordPolicyError):
        validate_password("", PasswordPolicy())


def test_strength_meter() -> None:
    assert password_strength("")[0] == 0
    assert password_strength("abc12345")[0] < password_strength("Abc12345!_longer")[0]
    assert password_strength("Abc12345!_longer")[1] == "بسیار قوی"
