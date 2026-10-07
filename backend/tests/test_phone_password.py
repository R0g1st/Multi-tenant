import pytest

from app.core.security import hash_password, normalize_phone, validate_password_strength, verify_password


@pytest.mark.parametrize("raw", ["8 (912) 345-67-89", "+7 912 345 67 89", "79123456789", "9123456789"])
def test_phone_normalized(raw):
    assert normalize_phone(raw) == "+79123456789"


def test_phone_invalid():
    with pytest.raises(ValueError):
        normalize_phone("123")


def test_password_hash_roundtrip():
    h = hash_password("Secret123")
    assert verify_password("Secret123", h)
    assert not verify_password("wrong", h)


def test_password_strength():
    validate_password_strength("Secret123")
    for bad in ("short1", "12345678", "onlyletters"):
        with pytest.raises(ValueError):
            validate_password_strength(bad)
