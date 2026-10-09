"""Курсы и обучение: создание курса, назначение, изучение материалов, тест, результаты."""
import os
import random
import uuid
from datetime import date, timedelta

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
    state = {"orgs": [], "users": [], "courses": []}
    yield state
    get_settings.cache_clear()
    eng = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.bypass_rls','on',true)"))
        p = {"o": state["orgs"], "u": state["users"], "c": state["courses"]}
        c.execute(text("DELETE FROM test_attempts WHERE org_id = ANY(CAST(:o AS uuid[]))"), p)
        c.execute(text("DELETE FROM assignments WHERE org_id = ANY(CAST(:o AS uuid[]))"), p)
        c.execute(text("DELETE FROM courses WHERE id = ANY(CAST(:c AS uuid[]))"), p)
        c.execute(text("DELETE FROM library_items WHERE uploaded_by = ANY(CAST(:u AS uuid[]))"), p)
        c.execute(text("""DELETE FROM audit_logs WHERE org_id = ANY(CAST(:o AS uuid[]))
            OR actor_user_id = ANY(CAST(:u AS uuid[]))"""), p)
        c.execute(text("DELETE FROM employees WHERE org_id = ANY(CAST(:o AS uuid[]))"), p)
        c.execute(text("DELETE FROM users WHERE id = ANY(CAST(:u AS uuid[]))"), p)
        c.execute(text("DELETE FROM organizations WHERE id = ANY(CAST(:o AS uuid[]))"), p)


def test_training_flow(env):
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

    org_a, org_b = org("А"), org("Б")
    director, _ = make("center_admin")
    customer, _ = make("org_admin", org_a)
    worker, emp_a = make("employee", org_a)
    stranger, emp_b = make("employee", org_b)

    # курс: материал из библиотеки + тест из двух вопросов
    doc = client.post(f"{API}/library/items", headers=director,
                      files={"file": ("Инструкция.pdf", b"%PDF test", "application/pdf")}).json()
    course = client.post(f"{API}/courses", headers=director, json={
        "title": f"Вводный инструктаж {tag}", "pass_score": 100, "validity_months": 12})
    assert course.status_code == 201, course.text
    course = course.json()
    env["courses"].append(course["id"])
    cid = course["id"]
    assert client.put(f"{API}/courses/{cid}/materials", headers=director,
                      json={"item_ids": [doc["id"]]}).json()["materials"][0]["title"] == "Инструкция"
    bad = client.put(f"{API}/courses/{cid}/test", headers=director, json={"questions": [
        {"text": "Без верного", "options": [{"text": "a"}, {"text": "b"}]}]})
    assert bad.status_code == 422
    test = [{"text": "Огнетушитель?", "options": [{"text": "красный", "correct": True}, {"text": "синий"}]},
            {"text": "СИЗ?", "multiple": True, "options": [
                {"text": "каска", "correct": True}, {"text": "перчатки", "correct": True}, {"text": "зонт"}]}]
    assert client.put(f"{API}/courses/{cid}/test", headers=director,
                      json={"questions": test}).status_code == 200

    # материал курса нельзя удалить из библиотеки
    assert client.delete(f"{API}/library/items/{doc['id']}", headers=director).status_code == 409
    # каталог курсов заказчик видит, редактировать не может; работник не видит
    assert any(c["id"] == cid for c in client.get(f"{API}/courses", headers=customer).json())
    assert client.patch(f"{API}/courses/{cid}", headers=customer, json={"title": "X"}).status_code == 403
    assert client.get(f"{API}/courses", headers=worker).status_code == 403

    # заказчик назначает курс своему работнику; повтор пропускается; чужого работника не видит
    due = (date.today() + timedelta(days=7)).isoformat()
    r = client.post(f"{API}/assignments", headers=customer,
                    json={"course_id": cid, "employee_ids": [str(emp_a)], "due_date": due})
    assert r.status_code == 201 and r.json()["created"] == 1, r.text
    assert client.post(f"{API}/assignments", headers=customer,
                       json={"course_id": cid, "employee_ids": [str(emp_a)]}).json()["skipped"]
    assert client.post(f"{API}/assignments", headers=customer,
                       json={"course_id": cid, "employee_ids": [str(emp_b)]}).status_code == 404

    # работник видит курс, тест закрыт до изучения материалов, правильные ответы скрыты
    mine = client.get(f"{API}/my/assignments", headers=worker).json()
    assert len(mine) == 1 and mine[0]["state"] == "assigned"
    aid = mine[0]["id"]
    detail = client.get(f"{API}/my/assignments/{aid}", headers=worker).json()
    assert detail["can_take_test"] is False and "correct" not in str(detail["test"])
    answers = {"answers": [[0], [0, 1]]}
    assert client.post(f"{API}/my/assignments/{aid}/test", headers=worker, json=answers).status_code == 409

    # чужой работник курс не откроет
    assert client.get(f"{API}/my/assignments/{aid}", headers=stranger).status_code == 404
    assert client.post(f"{API}/my/assignments/{aid}/materials/{doc['id']}", headers=stranger).status_code == 404

    # открытие материала: ссылка работает, прогресс засчитан
    link = client.post(f"{API}/my/assignments/{aid}/materials/{doc['id']}", headers=worker)
    assert link.status_code == 200
    assert client.get(link.json()["url"]).content == b"%PDF test"
    detail = client.get(f"{API}/my/assignments/{aid}", headers=worker).json()
    assert detail["can_take_test"] and detail["assignment"]["state"] == "in_progress"

    # неудачная попытка, затем успешная
    r = client.post(f"{API}/my/assignments/{aid}/test", headers=worker, json={"answers": [[1], [0]]}).json()
    assert r == {"score": 0, "passed": False, "correct": 0, "total": 2, "pass_score": 100}
    assert client.post(f"{API}/my/assignments/{aid}/test", headers=worker,
                       json={"answers": [[0, 1], [0]]}).status_code == 422  # один ответ в первом вопросе
    r = client.post(f"{API}/my/assignments/{aid}/test", headers=worker, json=answers).json()
    assert r["passed"] and r["score"] == 100
    assert client.post(f"{API}/my/assignments/{aid}/test", headers=worker, json=answers).status_code == 409

    # заказчик видит результат своего работника; директор — по всем, с фильтрами
    res = client.get(f"{API}/assignments", headers=customer).json()
    assert len(res) == 1 and res[0]["state"] == "passed" and res[0]["score"] == 100
    assert res[0]["attempts"] == 2 and res[0]["expires_at"]
    assert client.get(f"{API}/assignments", headers=director,
                      params={"org_id": str(org_a), "state": "passed"}).json()[0]["id"] == aid
    assert client.get(f"{API}/assignments", headers=director, params={"org_id": str(org_b)}).json() == []
    assert client.get(f"{API}/assignments", headers=worker).status_code == 403

    # после прохождения курс можно назначить повторно (переаттестация)
    assert client.post(f"{API}/assignments", headers=director,
                       json={"course_id": cid, "employee_ids": [str(emp_a)]}).json()["created"] == 1
