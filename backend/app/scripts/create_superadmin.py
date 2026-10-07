"""Создаёт первого суперадминистратора из переменных окружения.
Запуск: docker compose exec backend python -m app.scripts.create_superadmin
"""
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.security import hash_password, normalize_phone, validate_password_strength
from app.models import User


def main() -> None:
    s = get_settings()
    if not s.superadmin_phone or not s.superadmin_password:
        raise SystemExit("Задайте SUPERADMIN_PHONE и SUPERADMIN_PASSWORD в .env")
    phone = normalize_phone(s.superadmin_phone)
    validate_password_strength(s.superadmin_password)
    with tenant_session(bypass=True) as db:
        if db.scalar(select(User).where(User.phone == phone)):
            print("Пользователь с таким телефоном уже существует.")
            return
        db.add(User(phone=phone, password_hash=hash_password(s.superadmin_password),
                    full_name=s.superadmin_name, role="superadmin", must_change_password=True))
    print(f"Суперадминистратор создан: {phone}. Пароль нужно сменить при первом входе.")


if __name__ == "__main__":
    main()
