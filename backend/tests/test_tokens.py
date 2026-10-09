import jwt
import pytest
import uuid

from app.core.tokens import create_access_token, decode_access_token, hash_token, new_refresh_token
from app.core.security import generate_temp_password, validate_password_strength


def test_access_token_roundtrip(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    uid = uuid.uuid4()
    assert decode_access_token(create_access_token(uid))["sub"] == str(uid)


def test_bad_token_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token("not-a-token")


def test_refresh_token_hash():
    raw, hashed = new_refresh_token()
    assert hashed == hash_token(raw) and raw != hashed and len(hashed) == 64


def test_temp_password_is_valid():
    for _ in range(50):
        validate_password_strength(generate_temp_password())
