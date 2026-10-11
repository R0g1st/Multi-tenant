"""Книга паролей: просмотр паролей пользователей. Только главный администратор.

Пароли открываются мастер-паролем, который вводится при каждом просмотре и нигде не хранится.
Ответы запрещено кэшировать (браузеру и промежуточным серверам).
"""
import time
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import password_book as book
from app.core.db import tenant_session
from app.core.deps import Actor, get_db, require_roles
from app.models import Organization, User
from app.services import password_book
from app.services.audit import client_ip, log

router = APIRouter(prefix="/password-book", tags=["password-book"])
ADMIN = require_roles("superadmin")

MAX_FAILS, LOCK_SECONDS = 5, 15 * 60
_fails: dict[UUID, tuple[int, float]] = {}  # пользователь → (неудачных попыток, заблокирован до)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


def _check_lock(actor: Actor) -> None:
    fails, until = _fails.get(actor.id, (0, 0.0))
    if until > time.time():
        minutes = int((until - time.time()) // 60) + 1
        raise HTTPException(429, f"Слишком много неверных попыток. Попробуйте через {minutes} мин.")


def _open(actor: Actor, request: Request, action):
    """Выполняет action() с мастер-паролем, с защитой от перебора; возвращает его результат."""
    _check_lock(actor)
    try:
        result = action()
    except book.WrongPassphrase:
        fails = _fails.get(actor.id, (0, 0.0))[0] + 1
        _fails[actor.id] = (0, time.time() + LOCK_SECONDS) if fails >= MAX_FAILS else (fails, 0.0)
        with tenant_session(bypass=True) as own:  # отдельная транзакция: запрос завершится ошибкой
            log(own, actor=actor, action="password_book.wrong_passphrase", entity_type="password_book",
                ip=client_ip(request), description=f"{actor.full_name}: неверный мастер-пароль книги паролей")
        raise HTTPException(403, "Неверный мастер-пароль")
    except book.BookError as exc:
        raise HTTPException(409, str(exc))
    _fails.pop(actor.id, None)
    return result


class StatusOut(BaseModel):
    initialized: bool


class PassphraseIn(BaseModel):
    passphrase: str = Field(max_length=200)


class ChangePassphraseIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class BookEntry(BaseModel):
    user_id: UUID
    full_name: str
    phone: str
    role: str
    org_name: str | None
    is_active: bool
    password: str | None  # None — пароль задан до создания книги, его можно только сбросить
    source: str | None
    set_at: datetime | None
    set_by: str | None


@router.get("/status", response_model=StatusOut)
def status(response: Response, actor: Actor = Depends(ADMIN)):
    _no_store(response)
    return StatusOut(initialized=book.is_initialized(password_book.book_dir()))


@router.post("/init", response_model=StatusOut, status_code=201)
def init(body: PassphraseIn, request: Request, response: Response,
         actor: Actor = Depends(ADMIN), db=Depends(get_db)):
    _no_store(response)
    try:
        book.init(password_book.book_dir(), body.passphrase)
    except book.BookError as exc:
        raise HTTPException(409 if book.is_initialized(password_book.book_dir()) else 422, str(exc))
    log(db, actor=actor, action="password_book.init", entity_type="password_book", ip=client_ip(request),
        description=f"{actor.full_name} создал книгу паролей")
    return StatusOut(initialized=True)


@router.post("/unlock", response_model=list[BookEntry])
def unlock(body: PassphraseIn, request: Request, response: Response,
           actor: Actor = Depends(ADMIN), db=Depends(get_db)):
    """Расшифровывает книгу и отдаёт всех пользователей с их текущими паролями."""
    _no_store(response)
    latest = _open(actor, request, lambda: password_book.latest_by_user(body.passphrase))
    rows = db.execute(select(User, Organization.name).outerjoin(Organization, Organization.id == User.org_id)
                      .order_by(User.full_name)).all()
    items = []
    for user, org_name in rows:
        rec = latest.get(str(user.id))
        items.append(BookEntry(
            user_id=user.id, full_name=user.full_name, phone=user.phone, role=user.role,
            org_name=org_name, is_active=user.is_active,
            password=rec["password"] if rec else None,
            source=password_book.SOURCES.get(rec["source"], rec["source"]) if rec else None,
            set_at=rec["at"] if rec else None, set_by=rec.get("by") if rec else None))
    log(db, actor=actor, action="password_book.view", entity_type="password_book", ip=client_ip(request),
        description=f"{actor.full_name} открыл книгу паролей")
    return items


@router.post("/passphrase", status_code=204)
def change_passphrase(body: ChangePassphraseIn, request: Request,
                      actor: Actor = Depends(ADMIN), db=Depends(get_db)):
    _open(actor, request,
          lambda: book.change_passphrase(password_book.book_dir(), body.current, body.new))
    log(db, actor=actor, action="password_book.passphrase", entity_type="password_book",
        ip=client_ip(request), description=f"{actor.full_name} сменил мастер-пароль книги паролей")
