"""Запись выданных и изменённых паролей в книгу паролей главного администратора.

Вызывается везде, где пароль задаётся открытым текстом (выдача доступа, сброс, создание
пользователя, смена пароля самим пользователем, консольные команды). Если книга ещё не
создана или запись не удалась, действие с паролем всё равно выполняется — в журнал сервера
пишется предупреждение.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.core import password_book
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# откуда пароль: показывается в книге
SOURCES = {
    "issued": "выдан при создании доступа",
    "reset": "сброшен администратором",
    "changed": "изменён самим пользователем",
    "console": "задан из консоли",
    "vault": "загружен из файла паролей",
}


def book_dir() -> Path:
    return Path(get_settings().storage_dir) / "password_book"


def record(user, password: str, source: str, by: str | None = None) -> None:
    folder = book_dir()
    if not password_book.is_initialized(folder):
        return
    try:
        password_book.append(folder, {
            "user_id": str(user.id), "phone": user.phone, "full_name": user.full_name,
            "password": password, "source": source, "by": by,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    except Exception:  # пароль уже задан в БД — не ломаем действие из-за книги
        logger.exception("Не удалось записать пароль в книгу паролей (пользователь %s)", user.id)


def latest_by_user(passphrase: str) -> dict[str, dict]:
    """Последняя запись по каждому пользователю."""
    latest: dict[str, dict] = {}
    for rec in password_book.read_all(book_dir(), passphrase):
        latest[rec["user_id"]] = rec
    return latest
