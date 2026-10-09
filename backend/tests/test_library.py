"""Библиотека: права ролей, папки, загрузка и выдача файлов по подписанной ссылке."""
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
    state = {"orgs": [], "users": [], "folders": [], "items": []}
    yield state
    get_settings.cache_clear()
    eng = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.bypass_rls','on',true)"))
        p = {"o": state["orgs"], "u": state["users"]}
        c.execute(text("DELETE FROM library_items WHERE uploaded_by = ANY(CAST(:u AS uuid[]))"), p)
        c.execute(text("DELETE FROM library_folders WHERE id = ANY(CAST(:f AS uuid[]))"),
                  {"f": state["folders"][::-1]})
        c.execute(text("DELETE FROM audit_logs WHERE actor_user_id = ANY(CAST(:u AS uuid[]))"), p)
        c.execute(text("DELETE FROM users WHERE id = ANY(CAST(:u AS uuid[]))"), p)
        c.execute(text("DELETE FROM organizations WHERE id = ANY(CAST(:o AS uuid[]))"), p)


def test_library(env, tmp_path):
    from fastapi.testclient import TestClient
    from app.core.db import tenant_session
    from app.core.security import hash_password
    from app.main import app
    from app.models import Organization, User

    client = TestClient(app)
    tag = uuid.uuid4().hex[:6]

    def make(role, org_id=None):
        phone = rnd_phone()
        with tenant_session(bypass=True) as db:
            u = User(phone=phone, password_hash=hash_password(PW), full_name=f"{role} {tag}",
                     role=role, org_id=org_id, must_change_password=False)
            db.add(u)
            db.flush()
            env["users"].append(u.id)
        r = client.post(f"{API}/auth/login", json={"phone": phone, "password": PW})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    with tenant_session(bypass=True) as db:
        org = Organization(name=f"Орг {tag}")
        db.add(org)
        db.flush()
        env["orgs"].append(org.id)

    director = make("center_admin")
    customer = make("org_admin", org.id)
    worker = make("employee", org.id)

    # подчинённому библиотека недоступна; заказчик её читает (общую и свою)
    assert client.get(f"{API}/library/folders", headers=worker).status_code == 403
    assert client.post(f"{API}/library/folders", headers=worker, json={"name": "X"}).status_code == 403
    assert client.get(f"{API}/library/folders", headers=customer).status_code == 200

    # папки: создание, вложенность, дубль названия, защита от циклов
    top = client.post(f"{API}/library/folders", headers=director, json={"name": f"Охрана труда {tag}"})
    assert top.status_code == 201, top.text
    top = top.json()
    env["folders"].append(top["id"])
    sub = client.post(f"{API}/library/folders", headers=director,
                      json={"name": "Инструктажи", "parent_id": top["id"]}).json()
    env["folders"].append(sub["id"])
    assert client.post(f"{API}/library/folders", headers=director,
                       json={"name": "инструктажи", "parent_id": top["id"]}).status_code == 409
    assert client.patch(f"{API}/library/folders/{top['id']}", headers=director,
                        json={"parent_id": sub["id"]}).status_code == 422

    # загрузка документа и видео; неподдерживаемый тип отклоняется
    doc = client.post(f"{API}/library/items", headers=director, data={"folder_id": sub["id"]},
                      files={"file": ("Инструкция.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert doc.status_code == 201, doc.text
    doc = doc.json()
    assert doc["kind"] == "document" and doc["title"] == "Инструкция" and doc["size"] == 13
    video = client.post(f"{API}/library/items", headers=director,
                        data={"folder_id": sub["id"], "title": "Видеоурок"},
                        files={"file": ("lesson.mp4", b"0123456789" * 100, "video/mp4")}).json()
    assert video["kind"] == "video"
    assert client.post(f"{API}/library/items", headers=director,
                       files={"file": ("virus.exe", b"MZ", "application/octet-stream")}).status_code == 422
    assert len(list((tmp_path / "library").iterdir())) == 2

    listed = client.get(f"{API}/library/items", headers=director, params={"folder_id": sub["id"]}).json()
    assert {i["id"] for i in listed} == {doc["id"], video["id"]}
    folders = {f["id"]: f for f in client.get(f"{API}/library/folders", headers=director).json()}
    assert folders[sub["id"]]["items"] == 2

    # файл — только по подписанной ссылке; видео отдаётся кусками (перемотка)
    url = client.get(f"{API}/library/items/{video['id']}/link", headers=director).json()["url"]
    part = client.get(url, headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and part.content == b"0123456789"
    assert client.get(f"{API}/library/files/{video['id']}?t=bad").status_code == 403
    doc_url = client.get(f"{API}/library/items/{doc['id']}/link", headers=director).json()["url"]
    assert client.get(doc_url.replace(doc["id"], video["id"])).status_code == 403

    # непустую папку удалить нельзя; перенос материала в корень
    assert client.delete(f"{API}/library/folders/{sub['id']}", headers=director).status_code == 409
    moved = client.patch(f"{API}/library/items/{doc['id']}", headers=director, json={"folder_id": None})
    assert moved.status_code == 200 and moved.json()["folder_id"] is None

    # удаление материала убирает и файл с диска
    assert client.delete(f"{API}/library/items/{video['id']}", headers=director).status_code == 204
    assert client.get(url).status_code == 404
    assert len(list((tmp_path / "library").iterdir())) == 1
    assert client.delete(f"{API}/library/folders/{sub['id']}", headers=director).status_code == 204

    # общую папку заказчик видит, но изменять не может
    assert client.get(f"{API}/library/items", headers=customer, params={"folder_id": top["id"]}).status_code == 200
    assert client.patch(f"{API}/library/folders/{top['id']}", headers=customer,
                        json={"name": "Взлом"}).status_code == 403
    assert client.delete(f"{API}/library/items/{doc['id']}", headers=customer).status_code == 403
