"""Книга паролей главного администратора (папка storage/password_book/).

Хранится отдельно от базы сайта. Сайт умеет только ДОПИСЫВАТЬ записи и прочитать их
не может: каждая запись шифруется открытым ключом (X25519 + AES-256-GCM).
Закрытый ключ лежит в key.json зашифрованным мастер-паролем главного администратора
(scrypt + AES-256-GCM) и расшифровывается только в памяти, на время одного запроса
«показать пароли». Сам мастер-пароль нигде не сохраняется: без него файл не прочитать
ни с сервера, ни из резервной копии, ни через базу данных.

Файлы:
    key.json     {"version": 1, "public": ..., "salt": ..., "nonce": ..., "private": ...} (base64)
    entries.log  по строке на запись: base64(эфемерный ключ).base64(nonce).base64(шифртекст)
"""
import base64
import hashlib
import json
import os
import threading
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

try:  # блокировка файла между процессами (в контейнере — Linux)
    import fcntl
except ImportError:  # pragma: no cover — запуск на Windows без Docker
    fcntl = None

KEY_FILE = "key.json"
ENTRIES_FILE = "entries.log"
MIN_PASSPHRASE = 12
_KEY_AAD = b"ohs-password-book-key-v1"
_ENTRY_INFO = b"ohs-password-book-entry-v1"
_lock = threading.Lock()


class BookError(Exception):
    pass


class WrongPassphrase(BookError):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.b64decode(text)


def _kdf(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 15, r=8, p=1,
                          maxmem=64 * 1024 * 1024, dklen=32)


def _raw(key) -> bytes:
    if isinstance(key, X25519PublicKey):
        return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())


def _check_passphrase(passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE:
        raise BookError(f"Мастер-пароль должен быть не короче {MIN_PASSPHRASE} символов")


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _seal_private(private: X25519PrivateKey, passphrase: str) -> dict:
    salt, nonce = os.urandom(16), os.urandom(12)
    sealed = AESGCM(_kdf(passphrase, salt)).encrypt(nonce, _raw(private), _KEY_AAD)
    return {"version": 1, "public": _b64(_raw(private.public_key())),
            "salt": _b64(salt), "nonce": _b64(nonce), "private": _b64(sealed)}


def is_initialized(folder: Path) -> bool:
    return (folder / KEY_FILE).exists()


def init(folder: Path, passphrase: str) -> None:
    """Создаёт ключи. Повторно — нельзя: старые записи стали бы нечитаемыми."""
    _check_passphrase(passphrase)
    folder.mkdir(parents=True, exist_ok=True)
    if is_initialized(folder):
        raise BookError("Книга паролей уже создана")
    _write_atomic(folder / KEY_FILE, json.dumps(_seal_private(X25519PrivateKey.generate(), passphrase)).encode())


def _key_data(folder: Path) -> dict:
    if not is_initialized(folder):
        raise BookError("Книга паролей ещё не создана")
    return json.loads((folder / KEY_FILE).read_text())


def _open_private(folder: Path, passphrase: str) -> X25519PrivateKey:
    data = _key_data(folder)
    try:
        raw = AESGCM(_kdf(passphrase, _unb64(data["salt"]))).decrypt(
            _unb64(data["nonce"]), _unb64(data["private"]), _KEY_AAD)
    except InvalidTag:
        raise WrongPassphrase("Неверный мастер-пароль") from None
    return X25519PrivateKey.from_private_bytes(raw)


def change_passphrase(folder: Path, current: str, new: str) -> None:
    _check_passphrase(new)
    private = _open_private(folder, current)
    _write_atomic(folder / KEY_FILE, json.dumps(_seal_private(private, new)).encode())


def _entry_key(shared: bytes, eph_pub: bytes, pub: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=_ENTRY_INFO + eph_pub + pub).derive(shared)


def append(folder: Path, record: dict) -> None:
    """Дописывает зашифрованную запись. Мастер-пароль для этого не нужен."""
    pub_raw = _unb64(_key_data(folder)["public"])
    eph = X25519PrivateKey.generate()
    eph_pub = _raw(eph.public_key())
    key = _entry_key(eph.exchange(X25519PublicKey.from_public_bytes(pub_raw)), eph_pub, pub_raw)
    nonce = os.urandom(12)
    sealed = AESGCM(key).encrypt(nonce, json.dumps(record, ensure_ascii=False).encode(), None)
    line = f"{_b64(eph_pub)}.{_b64(nonce)}.{_b64(sealed)}\n".encode()
    with _lock, open(folder / ENTRIES_FILE, "ab") as f:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_all(folder: Path, passphrase: str) -> list[dict]:
    """Все записи по порядку. Повреждённые строки пропускаются."""
    private = _open_private(folder, passphrase)
    pub_raw = _raw(private.public_key())
    path = folder / ENTRIES_FILE
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        try:
            eph_b64, nonce_b64, sealed_b64 = line.split(".")
            eph_pub = _unb64(eph_b64)
            key = _entry_key(private.exchange(X25519PublicKey.from_public_bytes(eph_pub)), eph_pub, pub_raw)
            records.append(json.loads(AESGCM(key).decrypt(_unb64(nonce_b64), _unb64(sealed_b64), None)))
        except (ValueError, InvalidTag):
            continue
    return records
