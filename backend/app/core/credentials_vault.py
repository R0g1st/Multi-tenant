"""Зашифрованный список «телефон → пароль» (файл storage/credentials.vault).

Ключ шифрования получается из мастер-пароля (scrypt), сами данные шифруются
Fernet (AES-128-CBC + HMAC-SHA256). Без мастер-пароля файл прочитать нельзя,
а любое изменение файла обнаруживается при расшифровке.

Формат файла: b"OHSV1" + 16 байт соли + токен Fernet с JSON внутри:
    {"entries": {"+79990000000": {"password": "...", "name": "..."}}}
"""
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_MAGIC = b"OHSV1"
_SALT_LEN = 16


class VaultError(Exception):
    pass


def _key(passphrase: str, salt: bytes) -> bytes:
    raw = hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 15, r=8, p=1,
                         maxmem=64 * 1024 * 1024, dklen=32)
    return base64.urlsafe_b64encode(raw)


def load(path: Path, passphrase: str) -> dict[str, dict]:
    """Возвращает {телефон: {"password": ..., "name": ...}}. Нет файла — пустой словарь."""
    if not path.exists():
        return {}
    data = path.read_bytes()
    if not data.startswith(_MAGIC):
        raise VaultError(f"{path.name}: это не файл паролей")
    salt = data[len(_MAGIC):len(_MAGIC) + _SALT_LEN]
    try:
        plain = Fernet(_key(passphrase, salt)).decrypt(data[len(_MAGIC) + _SALT_LEN:])
    except InvalidToken:
        raise VaultError("Неверный мастер-пароль или файл повреждён") from None
    return json.loads(plain)["entries"]


def save(path: Path, passphrase: str, entries: dict[str, dict]) -> None:
    """Шифрует и записывает файл целиком (через временный файл, чтобы не повредить при сбое)."""
    salt = os.urandom(_SALT_LEN)
    token = Fernet(_key(passphrase, salt)).encrypt(
        json.dumps({"entries": entries}, ensure_ascii=False).encode())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_MAGIC + salt + token)
    os.replace(tmp, path)
