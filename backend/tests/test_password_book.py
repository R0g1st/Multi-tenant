import os
import random
import uuid

import pytest
from sqlalchemy import create_engine, text

from app.core import password_book as book

PASS = "очень-длинный-мастер-пароль"


def test_book_roundtrip_and_encrypted(tmp_path):
    book.init(tmp_path, PASS)
    book.append(tmp_path, {"user_id": "u1", "phone": "+79990001122", "password": "Секрет_123"})
    raw = (tmp_path / book.ENTRIES_FILE).read_bytes() + (tmp_path / book.KEY_FILE).read_bytes()
    assert b"79990001122" not in raw and "Секрет_123".encode() not in raw
    assert book.read_all(tmp_path, PASS) == [{"user_id": "u1", "phone": "+79990001122", "password": "Секрет_123"}]


def test_book_wrong_passphrase_and_change(tmp_path):
    book.init(tmp_path, PASS)
    book.append(tmp_path, {"user_id": "u1", "password": "a1b2c3d4"})
    with pytest.raises(book.WrongPassphrase):
        book.read_all(tmp_path, "не тот мастер-пароль")
    book.change_passphrase(tmp_path, PASS, "новый-мастер-пароль")
    with pytest.raises(book.WrongPassphrase):
        book.read_all(tmp_path, PASS)
    assert book.read_all(tmp_path, "новый-мастер-пароль")[0]["password"] == "a1b2c3d4"


def test_book_rules(tmp_path):
    with pytest.raises(book.BookError):
        book.init(tmp_path, "короткий")
    book.init(tmp_path, PASS)
    with pytest.raises(book.BookError):
        book.init(tmp_path, PASS)  # повторное создание сделало бы старые записи нечитаемыми


@pytest.mark.skipif(not (os.getenv("DATABASE_URL") and os.getenv("MIGRATION_DATABASE_URL")), reason="нет БД")
def test_only_superadmin_sees_passwords():
    from fastapi.testclient import TestClient
    from app.api.v1 import password_book as api_module
    from app.core.db import tenant_session
    from app.core.security import hash_password
    from app.main import app
    from app.models import User

    api_module._fails.clear()
    client = TestClient(app)
    phones = ["+7913" + "".join(str(random.randint(0, 9)) for _ in range(7)) for _ in range(2)]
    ids = []
    with tenant_session(bypass=True) as db:
        for phone, role in zip(phones, ("superadmin", "center_admin")):
            u = User(phone=phone, password_hash=hash_password("Passw0rd1"), full_name=f"Тест {uuid.uuid4().hex[:4]}",
                     role=role, must_change_password=False)
            db.add(u)
            db.flush()
            ids.append(u.id)
    try:
        def hdr(phone):
            r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "Passw0rd1"})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}
        sa, director = hdr(phones[0]), hdr(phones[1])

        # директору книга недоступна
        assert client.get("/api/v1/password-book/status", headers=director).status_code == 403
        assert client.post("/api/v1/password-book/unlock", headers=director, json={"passphrase": PASS}).status_code == 403

        assert client.get("/api/v1/password-book/status", headers=sa).json() == {"initialized": False}
        assert client.post("/api/v1/password-book/init", headers=sa, json={"passphrase": PASS}).status_code == 201

        # пароль, выданный после создания книги, виден главному администратору
        r = client.post(f"/api/v1/users/{ids[1]}/reset-password", headers=sa, json={"password": "Director2026"})
        assert r.status_code == 200, r.text
        r = client.post("/api/v1/password-book/unlock", headers=sa, json={"passphrase": PASS})
        assert r.status_code == 200, r.text
        assert "no-store" in r.headers["cache-control"]
        entry = next(i for i in r.json() if i["user_id"] == str(ids[1]))
        assert entry["password"] == "Director2026" and entry["phone"] == phones[1]
        assert next(i for i in r.json() if i["user_id"] == str(ids[0]))["password"] is None

        # неверный мастер-пароль; после 5 попыток — пауза
        for _ in range(5):
            assert client.post("/api/v1/password-book/unlock", headers=sa,
                               json={"passphrase": "неверный-мастер-пароль"}).status_code == 403
        assert client.post("/api/v1/password-book/unlock", headers=sa, json={"passphrase": PASS}).status_code == 429
    finally:
        api_module._fails.clear()
        eng = create_engine(os.environ["MIGRATION_DATABASE_URL"])
        with eng.begin() as c:
            c.execute(text("SELECT set_config('app.bypass_rls','on',true)"))
            p = {"u": [str(i) for i in ids]}
            c.execute(text("DELETE FROM audit_logs WHERE actor_user_id = ANY(CAST(:u AS uuid[])) "
                           "OR entity_id = ANY(CAST(:u AS text[]))"), p)
            c.execute(text("DELETE FROM refresh_sessions WHERE user_id = ANY(CAST(:u AS uuid[]))"), p)
            c.execute(text("DELETE FROM users WHERE id = ANY(CAST(:u AS uuid[]))"), p)
