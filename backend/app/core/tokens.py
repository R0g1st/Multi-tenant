import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings


def create_access_token(user_id) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "typ": "access", "iat": now,
               "exp": now + timedelta(minutes=s.access_token_minutes)}
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"],
                         options={"require": ["exp", "sub"]})
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """(сырой токен для клиента, хеш для хранения в БД)"""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


FILE_LINK_HOURS = 3  # хватает, чтобы досмотреть длинное видео с перемоткой


def create_file_token(item_id) -> str:
    """Подписанная ссылка на файл: <video> и <a> не умеют передавать заголовок Authorization."""
    now = datetime.now(timezone.utc)
    payload = {"sub": str(item_id), "typ": "file", "iat": now, "exp": now + timedelta(hours=FILE_LINK_HOURS)}
    return jwt.encode(payload, get_settings().secret_key, algorithm="HS256")


def decode_file_token(token: str) -> str:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"],
                         options={"require": ["exp", "sub"]})
    if payload.get("typ") != "file":
        raise jwt.InvalidTokenError("wrong token type")
    return payload["sub"]
