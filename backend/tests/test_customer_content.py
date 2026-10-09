"""Свои материалы и курсы заказчика: изоляция от других заказчиков и от общей библиотеки."""
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
def env(tmp_path, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    state = {"orgs": [], "users": []}
    yield state
    get_settings.cache_clear()
    eng = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.bypass_rls','on',true)"))
        p = {"o": state["orgs"], "u": state["users"]}
        c.execute(text("DELETE FROM test_attempts WHERE org_id = ANY(CAST(:o AS uuid[]))"), p)
        c.execute(text("DELETE FROM assignments WHERE org_id = ANY(CAST(:o AS uuid[]))"), p)
        c.execute(text("""DELETE FROM courses WHERE org_id = ANY(CAST(:o AS uuid[])) OR id IN
            (SELECT course_id FROM course_materials cm JOIN library_items li ON li.id = cm.item_id
             WHERE li.uploaded_by = ANY(CAST(:u AS uuid[])))"""), p)
        c.execute(text("DELETE FROM library_items WHERE uploaded_by = ANY(CAST(:u AS uuid[]))"), p)
        c.execute(text("DELETE FROM library_folders WHERE org_id = ANY(CAST(:o AS uuid[]))"), p)
        c.execute(text("""DELETE FROM audit_logs WHERE org_id = ANY(CAST(:o AS uuid[]))
            OR actor_user_id = ANY(CAST(:u AS uuid[]))"""), p)
        c.execute(text("DELETE FROM employees WHERE org_id = ANY(CAST(:o AS uuid[]))"), p)
        c.execute(text("DELETE FROM users WHERE id = ANY(CAST(:u AS uuid[]))"), p)
        c.execute(text("DELETE FROM organizations WHERE id = ANY(CAST(:o AS uuid[]))"), p)


def test_customer_content(env):
    from fastapi.testclient import TestClient
    from app.core.db import tenant_session
    from app.core.security import hash_password
    from app.main import app
    from app.models import Employee, Organization, User

    client = TestClient(app)
    tag = uuid.uuid4().hex[:6]

    def org(name):
        with tenant_session(bypass=True) as db:
            o = Organization(name=f"{name} {tag}")
            db.add(o)
            db.flush()
            env["orgs"].append(o.id)
            return o.id

    def make(role, org_id=None):
        phone = rnd_phone()
        with tenant_session(bypass=True) as db:
            u = User(phone=phone, password_hash=hash_password(PW), full_name=f"{role} {tag}",
                     role=role, org_id=org_id, must_change_password=False)
            db.add(u)
            db.flush()
            env["users"].append(u.id)
            emp_id = None
            if role == "employee":
                e = Employee(org_id=org_id, user_id=u.id, full_name=u.full_name, phone=phone)
                db.add(e)
                db.flush()
                emp_id = e.id
        r = client.post(f"{API}/auth/login", json={"phone": phone, "password": PW})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}, emp_id

    def upload(h, name, **data):
        r = client.post(f"{API}/library/items", headers=h, data=data,
                        files={"file": (name, b"%PDF " + name.encode(), "application/pdf")})
        assert r.status_code == 201, r.text
        return r.json()

    org_a, org_b = org("А"), org("Б")
    director, _ = make("center_admin")
    cust_a, _ = make("org_admin", org_a)
    cust_b, _ = make("org_admin", org_b)
    worker_a, emp_a = make("employee", org_a)
    _, emp_b = make("employee", org_b)

    shared = upload(director, "Общий.pdf")
    assert shared["org_id"] is None

    # заказчик А: своя папка и свой материал — всегда в своей библиотеке
    folder = client.post(f"{API}/library/folders", headers=cust_a, json={"name": "Наши инструкции"})
    assert folder.status_code == 201 and folder.json()["org_id"] == str(org_a)
    folder = folder.json()
    own = upload(cust_a, "Свой.pdf", folder_id=folder["id"])
    assert own["org_id"] == str(org_a)
    # даже если попросит общую — получит свою
    root_own = upload(cust_a, "В корень.pdf")
    assert root_own["org_id"] == str(org_a)
    # в общую папку загрузить нельзя
    shared_folder = client.post(f"{API}/library/folders", headers=director, json={"name": f"Общая {tag}"}).json()
    r = client.post(f"{API}/library/items", headers=cust_a, data={"folder_id": shared_folder["id"]},
                    files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 403
    client.delete(f"{API}/library/folders/{shared_folder['id']}", headers=director)

    # заказчик Б не видит материалов А — ни в списке, ни по ссылке, ни по прямому id
    assert client.get(f"{API}/library/folders", headers=cust_b, params={"owner": str(org_a)}).status_code == 403
    assert client.get(f"{API}/library/items", headers=cust_b,
                      params={"folder_id": folder["id"]}).status_code == 404
    assert client.get(f"{API}/library/items/{own['id']}/link", headers=cust_b).status_code == 404
    assert client.patch(f"{API}/library/items/{own['id']}", headers=cust_b, json={"title": "X"}).status_code == 404
    # своё А видит; директор видит библиотеку А
    titles = {i["title"] for i in client.get(f"{API}/library/items", headers=cust_a,
                                             params={"folder_id": folder["id"]}).json()}
    assert titles == {"Свой"}
    assert {f["id"] for f in client.get(f"{API}/library/folders", headers=director,
                                        params={"owner": str(org_a)}).json()} == {folder["id"]}

    # курс заказчика А: общий материал + свой
    course = client.post(f"{API}/courses", headers=cust_a, json={"title": f"Курс А {tag}"}).json()
    assert course["org_id"] == str(org_a) and course["editable"]
    r = client.put(f"{API}/courses/{course['id']}/materials", headers=cust_a,
                   json={"item_ids": [shared["id"], own["id"]]})
    assert r.status_code == 200, r.text
    assert [m["title"] for m in r.json()["materials"]] == ["Общий", "Свой"]

    # общий курс директора нельзя собрать из материалов заказчика
    common = client.post(f"{API}/courses", headers=director, json={"title": f"Общий курс {tag}"}).json()
    assert common["org_id"] is None
    assert client.put(f"{API}/courses/{common['id']}/materials", headers=director,
                      json={"item_ids": [own["id"]]}).status_code == 422
    # общий курс заказчик видит, но изменить не может
    listed = {c["id"]: c for c in client.get(f"{API}/courses", headers=cust_a).json()}
    assert listed[common["id"]]["editable"] is False and listed[course["id"]]["editable"] is True
    assert client.patch(f"{API}/courses/{common['id']}", headers=cust_a, json={"title": "X"}).status_code == 403

    # заказчик Б не видит курс А; директор видит
    assert course["id"] not in {c["id"] for c in client.get(f"{API}/courses", headers=cust_b).json()}
    assert client.get(f"{API}/courses/{course['id']}", headers=cust_b).status_code == 404
    assert course["id"] in {c["id"] for c in client.get(f"{API}/courses", headers=director).json()}

    # курс А назначается только работникам А
    r = client.post(f"{API}/assignments", headers=director,
                    json={"course_id": course["id"], "employee_ids": [str(emp_a), str(emp_b)]}).json()
    assert r["created"] == 1 and "другого заказчика" in r["skipped"][0]

    # работник А открывает и общий, и свой материал курса
    aid = client.get(f"{API}/my/assignments", headers=worker_a).json()[0]["id"]
    for item in (shared, own):
        link = client.post(f"{API}/my/assignments/{aid}/materials/{item['id']}", headers=worker_a)
        assert link.status_code == 200 and client.get(link.json()["url"]).status_code == 200
    # без теста курс засчитан после изучения всех материалов
    assert client.get(f"{API}/my/assignments", headers=worker_a).json()[0]["state"] == "passed"
