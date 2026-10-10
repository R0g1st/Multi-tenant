import pytest


@pytest.fixture(autouse=True)
def isolated_password_book(tmp_path, monkeypatch):
    """Тесты пишут пароли во временную книгу, а не в настоящую storage/password_book."""
    from app.services import password_book
    folder = tmp_path / "password_book"
    monkeypatch.setattr(password_book, "book_dir", lambda: folder)
    return folder
