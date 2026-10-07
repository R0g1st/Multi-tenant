"""Проверка изоляции организаций на уровне БД (RLS).
Нужна работающая БД: TEST_DATABASE_URL (роль ohs_app) — иначе тесты пропускаются.
Запуск: docker compose exec backend pytest -q
"""
import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="нет DATABASE_URL")


@pytest.fixture
def two_orgs():
    from app.core.db import tenant_session
    from app.models import Employee, Organization

    tag = uuid.uuid4().hex[:8]
    with tenant_session(bypass=True) as db:
        a = Organization(name=f"A-{tag}")
        b = Organization(name=f"B-{tag}")
        db.add_all([a, b])
        db.flush()
        db.add_all([Employee(org_id=a.id, full_name=f"Иванов {tag}"),
                    Employee(org_id=b.id, full_name=f"Петров {tag}")])
        ids = (a.id, b.id)
    yield ids
    with tenant_session(bypass=True) as db:
        db.execute(text("DELETE FROM employees WHERE org_id = ANY(:i)"), {"i": list(ids)})
        db.execute(text("DELETE FROM organizations WHERE id = ANY(:i)"), {"i": list(ids)})


def test_org_sees_only_own_employees(two_orgs):
    from app.core.db import tenant_session
    from app.models import Employee
    a, b = two_orgs
    with tenant_session(org_id=a) as db:
        rows = db.scalars(select(Employee)).all()
        assert rows and all(r.org_id == a for r in rows)


def test_no_context_sees_nothing(two_orgs):
    from app.core.db import tenant_session
    from app.models import Employee, Organization
    with tenant_session() as db:
        assert db.scalars(select(Employee)).all() == []
        assert db.scalars(select(Organization)).all() == []


def test_cannot_write_into_foreign_org(two_orgs):
    from app.core.db import tenant_session
    from app.models import Employee
    a, b = two_orgs
    with pytest.raises(DBAPIError):
        with tenant_session(org_id=a) as db:
            db.add(Employee(org_id=b, full_name="Чужой"))
            db.flush()


def test_context_does_not_leak_between_transactions(two_orgs):
    from app.core.db import tenant_session
    a, _ = two_orgs
    with tenant_session(org_id=a):
        pass
    with tenant_session() as db:
        assert db.execute(text("SELECT app_current_org()")).scalar() is None
