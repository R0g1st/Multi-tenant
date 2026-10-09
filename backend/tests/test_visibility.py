"""Кто чьи входы видит: 1 — всё, 2 — всех, кроме 1, 3 — только своих подчинённых, 4 — никого."""
import os
import random
import uuid

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.skipif(
    not (os.getenv("DATABASE_URL") and os.getenv("MIGRATION_DATABASE_URL")), reason="нет БД")

API = "/api/v1"
PW = "Passw0rdTest"


def rnd_phone() -> str:
    return "+7912" + "".join(str(random.randint(0, 9)) for _ in range(7))


@pytest.fixture
def ctx():
    state = {"orgs": [], "users": []}
    yield state
    eng = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.bypass_rls','on',true)"))
        p = {"o": state["orgs"], "u": state["users"]}
        c.execute(text("""DELETE FROM audit_logs WHERE org_id = ANY(CAST(:o AS uuid[]))
            OR actor_user_id = ANY(CAST(:u AS uuid[]))"""), p)
        c.execute(text("DELETE FROM employees WHERE org_id = ANY(CAST(:o AS uuid[]))"), p)
        c.execute(text("DELETE FROM users WHERE id = ANY(CAST(:u AS uuid[]))"), p)
        c.execute(text("DELETE FROM organizations WHERE id = ANY(CAST(:o AS uuid[]))"), p)


def test_who_sees_whom(ctx):
    from fastapi.testclient import TestClient
    from app.core.db import tenant_session
    from app.core.security import hash_password
    from app.main import app
    from app.models import Employee, Organization, User

    client = TestClient(app)
    tag = uuid.uuid4().hex[:6]

    with tenant_session(bypass=True) as db:
        org = Organization(name=f"Орг {tag}")
        db.add(org)
        db.flush()
        ctx["orgs"].append(org.id)

    def make(role, org_id=None):
        phone = rnd_phone()
        with tenant_session(bypass=True) as db:
            u = User(phone=phone, password_hash=hash_password(PW), full_name=f"{role} {tag}",
                     role=role, org_id=org_id, must_change_password=False)
            db.add(u)
            db.flush()
            ctx["users"].append(u.id)
            if role == "employee":
                db.add(Employee(org_id=org_id, user_id=u.id, full_name=u.full_name, phone=phone))
        r = client.post(f"{API}/auth/login", json={"phone": phone, "password": PW})
        assert r.status_code == 200, r.text
        return u.id, {"Authorization": f"Bearer {r.json()['access_token']}"}

    sa_id, sa = make("superadmin")
    dir_id, director = make("center_admin")
    cust_id, customer = make("org_admin", org.id)
    _, worker = make("employee", org.id)

    # 1: видит всех, включая главного администратора, и его вход в журнале
    ids = {u["id"] for u in client.get(f"{API}/users?limit=200", headers=sa).json()["items"]}
    assert {str(sa_id), str(dir_id), str(cust_id)} <= ids
    sa_log = client.get(f"{API}/audit", headers=sa, params={"actor_user_id": str(sa_id)}).json()
    assert sa_log["total"] >= 1

    # 2: видит директоров и заказчиков, но не главного администратора — ни в списке, ни в журнале
    ids = {u["id"] for u in client.get(f"{API}/users?limit=200", headers=director).json()["items"]}
    assert str(dir_id) in ids and str(cust_id) in ids and str(sa_id) not in ids
    assert client.get(f"{API}/users", headers=director, params={"role": "superadmin"}).json()["total"] == 0
    assert client.patch(f"{API}/users/{sa_id}", headers=director, json={"is_active": False}).status_code == 404
    assert client.get(f"{API}/audit", headers=director,
                      params={"actor_user_id": str(sa_id)}).json()["total"] == 0
    assert client.get(f"{API}/audit", headers=director,
                      params={"actor_user_id": str(cust_id)}).json()["total"] >= 1

    # 3: видит вход своих подчинённых, но не список пользователей и не журнал
    emps = client.get(f"{API}/employees", headers=customer).json()["items"]
    assert emps and emps[0]["last_login_at"] is not None
    assert client.get(f"{API}/users", headers=customer).status_code == 403
    assert client.get(f"{API}/audit", headers=customer).status_code == 403

    # 4: не видит ничего о входах
    for path in ("/users", "/audit", "/employees"):
        assert client.get(f"{API}{path}", headers=worker).status_code == 403

    # 4: видит своего заказчика и его представителей — без сведений о входах
    mine = client.get(f"{API}/organizations/mine", headers=worker)
    assert mine.status_code == 200, mine.text
    mine = mine.json()
    assert mine["name"] == f"Орг {tag}"
    assert [c["full_name"] for c in mine["contacts"]] == [f"org_admin {tag}"]
    assert "last_login_at" not in str(mine)
    assert client.get(f"{API}/organizations/mine", headers=director).status_code == 403
