import pytest

from app.core import credentials_vault


def test_roundtrip_and_encrypted(tmp_path):
    path = tmp_path / "credentials.vault"
    entries = {"+79990000000": {"password": "Секрет_123", "name": "Иванов И.И."}}
    credentials_vault.save(path, "master-passphrase", entries)
    assert b"79990000000" not in path.read_bytes()
    assert "Секрет_123".encode() not in path.read_bytes()
    assert credentials_vault.load(path, "master-passphrase") == entries


def test_wrong_passphrase(tmp_path):
    path = tmp_path / "credentials.vault"
    credentials_vault.save(path, "master-passphrase", {})
    with pytest.raises(credentials_vault.VaultError):
        credentials_vault.load(path, "wrong-passphrase")


def test_missing_file_is_empty(tmp_path):
    assert credentials_vault.load(tmp_path / "nope.vault", "x") == {}
