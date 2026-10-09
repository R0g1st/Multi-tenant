"""Задать пароль пользователю напрямую в БД (пароль хешируется, в открытом виде не хранится).

Запуск:  docker compose exec backend python -m app.scripts.set_password
Можно сразу указать номер:  ... python -m app.scripts.set_password --phone +79990000000
"""
import argparse
import getpass
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.core.db import tenant_session
from app.core.security import hash_password, normalize_phone, validate_password_strength
from app.models import RefreshSession, User
from app.services.audit import log


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", help="номер телефона пользователя")
    args = parser.parse_args()

    phone = normalize_phone(args.phone or input("Номер телефона пользователя: "))
    password = getpass.getpass("Новый пароль (ввод не отображается): ")
    if password != getpass.getpass("Повторите пароль: "):
        raise SystemExit("Пароли не совпадают. Ничего не изменено.")
    try:
        validate_password_strength(password)
    except ValueError as exc:
        raise SystemExit(f"{exc}. Ничего не изменено.")

    with tenant_session(bypass=True) as db:
        user = db.scalar(select(User).where(User.phone == phone))
        if user is None:
            raise SystemExit("Пользователь с таким номером не найден. Ничего не изменено.")
        user.password_hash = hash_password(password)
        user.must_change_password = False
        user.failed_login_count = 0
        user.locked_until = None
        user.is_active = True
        user.updated_at = datetime.now(timezone.utc)
        db.execute(update(RefreshSession)
                   .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
                   .values(revoked_at=datetime.now(timezone.utc)))
        log(db, actor=None, actor_id=None, org_id=user.org_id, action="user.password_set_console",
            entity_type="user", entity_id=user.id,
            description=f"Пароль пользователя «{user.full_name}» задан через консоль сервера")
    print(f"Готово. Пароль для {phone} обновлён, активные сессии закрыты.")


if __name__ == "__main__":
    main()
