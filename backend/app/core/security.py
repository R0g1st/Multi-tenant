import phonenumbers
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()


def normalize_phone(raw: str) -> str:
    """Приводит номер к формату E.164 (+79123456789). ValueError, если номер неверный."""
    try:
        parsed = phonenumbers.parse(raw.strip(), get_settings().default_region)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Некорректный номер телефона") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Некорректный номер телефона")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Пароль должен содержать не менее 8 символов")
    if password.isdigit() or password.isalpha():
        raise ValueError("Пароль должен содержать буквы и цифры")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


import secrets as _secrets

_TEMP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def generate_temp_password(length: int = 10) -> str:
    """Временный пароль без похожих символов (0/O, 1/l/I). Всегда буквы + цифры."""
    while True:
        pw = "".join(_secrets.choice(_TEMP_ALPHABET) for _ in range(length))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw
