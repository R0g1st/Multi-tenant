"""Подключение к БД и контекст арендатора (тенанта).

Каждая транзакция получает переменные app.current_org / app.bypass_rls
через SET LOCAL (set_config(..., true)), поэтому они живут ровно до конца
транзакции и не могут «протечь» через пул соединений.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine = None
_SessionLocal = None


def _factory() -> sessionmaker:
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    return _SessionLocal


@contextmanager
def tenant_session(org_id: UUID | None = None, bypass: bool = False) -> Iterator[Session]:
    """Сессия в одной транзакции с заданным контекстом.

    org_id  — организация пользователя (видны только её строки);
    bypass  — только для сотрудников учебного центра и процедуры входа.
    Без org_id и без bypass не видно ни одной строки арендатора.
    """
    with _factory()() as session:
        with session.begin():
            session.execute(
                text("SELECT set_config('app.current_org', :org, true), "
                     "set_config('app.bypass_rls', :bypass, true)"),
                {"org": str(org_id) if org_id else "", "bypass": "on" if bypass else "off"},
            )
            yield session
