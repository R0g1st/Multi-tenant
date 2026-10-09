"""Перенос паролей из зашифрованного файла в БД.

Файл — главный источник: если пароль пользователя в БД не совпадает с паролем
из файла, в БД записывается хеш пароля из файла, активные сессии закрываются.
Пользователи, которых нет в файле, не затрагиваются.
"""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update

from app.core import credentials_vault
from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.security import hash_password, verify_password
from app.models import RefreshSession, User
from app.services.audit import log


def vault_path() -> Path:
    return Path(get_settings().storage_dir) / "credentials.vault"


def sync(passphrase: str) -> tuple[int, list[str]]:
    """Возвращает (сколько паролей обновлено, телефоны из файла без пользователя в БД)."""
    entries = credentials_vault.load(vault_path(), passphrase)
    changed, missing = 0, []
    now = datetime.now(timezone.utc)
    with tenant_session(bypass=True) as db:
        users = {u.phone: u for u in db.scalars(select(User).where(User.phone.in_(entries)))}
        for phone, entry in entries.items():
            user = users.get(phone)
            if user is None:
                missing.append(phone)
                continue
            if verify_password(entry["password"], user.password_hash) and not user.must_change_password:
                continue
            user.password_hash = hash_password(entry["password"])
            user.must_change_password = False
            user.failed_login_count = 0
            user.locked_until = None
            user.updated_at = now
            db.execute(update(RefreshSession)
                       .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
                       .values(revoked_at=now))
            log(db, actor=None, org_id=user.org_id, action="user.password_from_vault",
                entity_type="user", entity_id=user.id,
                description=f"Пароль пользователя «{user.full_name}» загружен из файла паролей")
            changed += 1
    return changed, missing
