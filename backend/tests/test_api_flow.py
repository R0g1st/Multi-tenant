"""Сквозной сценарий через HTTP: вход, роли, выдача доступа, изоляция организаций, аудит.
Нужна БД (DATABASE_URL и MIGRATION_DATABASE_URL внутри контейнера backend).
"""
import json
import os
import random
import uuid

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.skipif(
    not (os.getenv("DATABASE_URL") and os.getenv("MIGRATION_DATABASE_URL")), reason="нет БД")

API = "/api/v1"


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
            OR actor_user_id IN (SELECT id FROM users WHERE org_id = ANY(CAST(:o AS uuid[])) OR id = ANY(CAST(:u AS uuid[])))"""), p)
        for t in ("employees", "departments", "positions"):
            c.execute(text(f"DELETE FROM {t} WHERE org_id = ANY(CAST(:o AS uuid[]))"), p)
        c.execute(text("DELETE FROM users WHERE org_id = ANY(CAST(:o AS uuid[])) OR id = ANY(CAST(:u AS uuid[]))"), p)
        c.execute(text("DELETE FROM organizations WHERE id = ANY(CAST(:o AS uuid[]))"), p)


def test_full_flow(ctx):
    from fastapi.testclient import TestClient
    from app.core.db import tenant_session
    from app.core.security import hash_password
    from app.main import app
    from app.models import User

    client = TestClient(app)
    tag = uuid.uuid4().hex[:6]

    def login(phone, password):
        r = client.post(f"{API}/auth/login", json={"phone": phone, "password": password})
        assert r.status_code == 200, r.text
        return r.json()

    def hdr(tokens):
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    # суперадмин создаётся напрямую в БД
    sa_phone, sa_pw = rnd_phone(), "Superadm1n"
    with tenant_session(bypass=True) as db:
        sa = User(phone=sa_phone, password_hash=hash_password(sa_pw), full_name="Админ Тест",
                  role="superadmin", must_change_password=False)
        db.add(sa)
        db.flush()
        ctx["users"].append(sa.id)
    sa_h = hdr(login(sa_phone, sa_pw))

    # неверный пароль и вход без токена
    assert client.post(f"{API}/auth/login", json={"phone": sa_phone, "password": "wrong"}).status_code == 401
    assert client.get(f"{API}/organizations").status_code == 401

    # две организации
    org_a = client.post(f"{API}/organizations", json={"name": f"Орг А {tag}"}, headers=sa_h).json()
    org_b = client.post(f"{API}/organizations", json={"name": f"Орг Б {tag}"}, headers=sa_h).json()
    ctx["orgs"] += [org_a["id"], org_b["id"]]

    dept = client.post(f"{API}/departments", json={"name": "Цех 1", "org_id": org_a["id"]}, headers=sa_h)
    assert dept.status_code == 201, dept.text

    phone_a = rnd_phone()
    emp_a = client.post(f"{API}/employees", headers=sa_h, json={
        "org_id": org_a["id"], "full_name": f"Иванов {tag}", "phone": phone_a,
        "department_id": dept.json()["id"]})
    assert emp_a.status_code == 201, emp_a.text
    emp_b = client.post(f"{API}/employees", headers=sa_h,
                        json={"org_id": org_b["id"], "full_name": f"Петров {tag}"}).json()

    # подразделение другой организации назначить нельзя
    bad = client.post(f"{API}/employees", headers=sa_h, json={
        "org_id": org_b["id"], "full_name": "Х", "department_id": dept.json()["id"]})
    assert bad.status_code == 422

    # выдача доступа сотруднику
    grant = client.post(f"{API}/employees/{emp_a.json()['id']}/grant-access", headers=sa_h)
    assert grant.status_code == 200, grant.text
    temp_pw = grant.json()["temporary_password"]
    assert client.post(f"{API}/employees/{emp_a.json()['id']}/grant-access", headers=sa_h).status_code == 409

    emp_tokens = login(phone_a, temp_pw)
    assert emp_tokens["must_change_password"] is True
    r = client.get(f"{API}/employees", headers=hdr(emp_tokens))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "password_change_required"
    r = client.post(f"{API}/auth/change-password", headers=hdr(emp_tokens),
                    json={"current_password": temp_pw, "new_password": "NewSecret77"})
    assert r.status_code == 200, r.text
    new_tokens = r.json()
    me = client.get(f"{API}/auth/me", headers=hdr(new_tokens)).json()
    assert me["role"] == "employee" and me["org_id"] == org_a["id"]
    # сотрудник не имеет доступа к списку сотрудников
    assert client.get(f"{API}/employees", headers=hdr(new_tokens)).status_code == 403
    # старый refresh после смены пароля недействителен
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": emp_tokens["refresh_token"]}).status_code == 401

    # администратор организации А
    adm_phone = rnd_phone()
    created = client.post(f"{API}/users", headers=sa_h, json={
        "phone": adm_phone, "full_name": "Админ Орг А", "role": "org_admin", "org_id": org_a["id"]})
    assert created.status_code == 201, created.text
    adm_pw = created.json()["temporary_password"]
    adm = login(adm_phone, adm_pw)
    adm = client.post(f"{API}/auth/change-password", headers=hdr(adm),
                      json={"current_password": adm_pw, "new_password": "AdminPass99"}).json()
    adm_h = hdr(adm)

    items = client.get(f"{API}/employees", headers=adm_h).json()["items"]
    assert items and all(i["org_id"] == org_a["id"] for i in items)
    # чужого сотрудника не видно и менять нельзя
    assert client.get(f"{API}/employees/{emp_b['id']}", headers=adm_h).status_code == 404
    assert client.patch(f"{API}/employees/{emp_b['id']}", headers=adm_h, json={"full_name": "Взлом"}).status_code == 404
    # нельзя создать сотрудника в чужой организации
    assert client.post(f"{API}/employees", headers=adm_h,
                       json={"org_id": org_b["id"], "full_name": "Чужой"}).status_code == 403
    # чужую организацию не видно, создавать организации нельзя
    assert client.get(f"{API}/organizations/{org_b['id']}", headers=adm_h).status_code == 404
    assert client.post(f"{API}/organizations", headers=adm_h, json={"name": "Z"}).status_code == 403
    # журнал аудита недоступен администратору организации
    assert client.get(f"{API}/audit", headers=adm_h).status_code == 403

    # деактивация сотрудника закрывает доступ
    assert client.post(f"{API}/employees/{emp_a.json()['id']}/deactivate", headers=adm_h).status_code == 200
    assert client.get(f"{API}/auth/me", headers=hdr(new_tokens)).status_code == 401

    # аудит: действия записаны, пароль не попал в журнал
    audit = client.get(f"{API}/audit", params={"org_id": org_a["id"], "limit": 200}, headers=sa_h)
    assert audit.status_code == 200
    actions = {i["action"] for i in audit.json()["items"]}
    assert {"employee.create", "employee.grant_access", "employee.deactivate", "user.create"} <= actions
    dump = json.dumps(audit.json(), ensure_ascii=False)
    assert temp_pw not in dump and adm_pw not in dump
