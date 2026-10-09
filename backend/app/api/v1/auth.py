from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.deps import Actor, current_actor, org_is_usable
from app.core.security import hash_password, normalize_phone, verify_password
from app.core.tokens import create_access_token, hash_token, new_refresh_token
from app.models import RefreshSession, User
from app.schemas import ChangePasswordIn, LoginIn, MeOut, RefreshIn, TokenPair
from app.services.audit import client_ip, log

router = APIRouter(prefix="/auth", tags=["auth"])

# Для выравнивания времени ответа, когда пользователь не найден (против перебора номеров)
_DUMMY_HASH = hash_password("dummy-password-for-timing")
_BAD_CREDENTIALS = "Неверный телефон или пароль"


def _issue_tokens(db, user: User, request: Request, now: datetime) -> TokenPair:
    s = get_settings()
    raw, hashed = new_refresh_token()
    db.add(RefreshSession(
        user_id=user.id, token_hash=hashed, expires_at=now + timedelta(days=s.refresh_token_days),
        user_agent=(request.headers.get("user-agent") or "")[:300], ip=client_ip(request)))
    return TokenPair(access_token=create_access_token(user.id), refresh_token=raw,
                     expires_in=s.access_token_minutes * 60,
                     must_change_password=user.must_change_password)


def _revoke_all(db, user_id) -> None:
    db.execute(update(RefreshSession)
               .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))


@router.post("/login", response_model=TokenPair)
def login(body: LoginIn, request: Request) -> TokenPair:
    s = get_settings()
    ip = client_ip(request)
    now = datetime.now(timezone.utc)
    try:
        phone = normalize_phone(body.phone)
    except ValueError:
        verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(401, _BAD_CREDENTIALS)

    error: tuple[int, str] | None = None
    tokens: TokenPair | None = None
    # Ошибку выбрасываем только после выхода из транзакции, иначе счётчик попыток откатится.
    with tenant_session(bypass=True) as db:
        user = db.scalar(select(User).where(User.phone == phone).with_for_update())
        if user is None:
            verify_password(body.password, _DUMMY_HASH)
            error = (401, _BAD_CREDENTIALS)
        elif user.locked_until and user.locked_until > now:
            error = (429, "Слишком много неудачных попыток входа. Повторите позже.")
        elif not verify_password(body.password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= s.max_failed_logins:
                user.locked_until = now + timedelta(minutes=s.lock_minutes)
                user.failed_login_count = 0
                log(db, actor=None, actor_id=user.id, org_id=user.org_id, action="auth.locked",
                    entity_type="user", entity_id=user.id, ip=ip,
                    description=f"Учётная запись {user.full_name} временно заблокирована после неудачных попыток входа")
            error = (401, _BAD_CREDENTIALS)
        elif not user.is_active or not org_is_usable(db, user):
            error = (401, _BAD_CREDENTIALS)
        else:
            user.failed_login_count = 0
            user.locked_until = None
            user.last_login_at = now
            tokens = _issue_tokens(db, user, request, now)
            log(db, actor=None, actor_id=user.id, org_id=user.org_id, action="auth.login",
                entity_type="user", entity_id=user.id, ip=ip,
                description=f"{user.full_name} вошёл в систему")
    if error:
        raise HTTPException(*error)
    return tokens


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshIn, request: Request) -> TokenPair:
    now = datetime.now(timezone.utc)
    error = False
    tokens: TokenPair | None = None
    with tenant_session(bypass=True) as db:
        sess = db.scalar(select(RefreshSession)
                         .where(RefreshSession.token_hash == hash_token(body.refresh_token))
                         .with_for_update())
        if sess is None:
            error = True
        elif sess.revoked_at is not None:
            _revoke_all(db, sess.user_id)  # повторное использование старого токена: считаем его украденным
            error = True
        elif sess.expires_at <= now:
            error = True
        else:
            user = db.get(User, sess.user_id)
            if user is None or not user.is_active or not org_is_usable(db, user):
                error = True
            else:
                sess.revoked_at = now
                tokens = _issue_tokens(db, user, request, now)
    if error:
        raise HTTPException(401, "Сессия истекла, войдите заново")
    return tokens


@router.post("/logout", status_code=204)
def logout(body: RefreshIn) -> Response:
    with tenant_session(bypass=True) as db:
        db.execute(update(RefreshSession)
                   .where(RefreshSession.token_hash == hash_token(body.refresh_token),
                          RefreshSession.revoked_at.is_(None))
                   .values(revoked_at=datetime.now(timezone.utc)))
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
def me(actor: Actor = Depends(current_actor)) -> MeOut:
    return MeOut(id=actor.id, phone=actor.phone, full_name=actor.full_name, role=actor.role,
                 org_id=actor.org_id, must_change_password=actor.must_change_password)


@router.post("/change-password", response_model=TokenPair)
def change_password(body: ChangePasswordIn, request: Request,
                    actor: Actor = Depends(current_actor)) -> TokenPair:
    """Доступно и при must_change_password. Все прежние сессии закрываются, выдаётся новая пара токенов."""
    now = datetime.now(timezone.utc)
    error: str | None = None
    tokens: TokenPair | None = None
    with tenant_session(bypass=True) as db:
        user = db.get(User, actor.id)
        if not verify_password(body.current_password, user.password_hash):
            error = "Неверный текущий пароль"
        elif body.current_password == body.new_password:
            error = "Новый пароль должен отличаться от текущего"
        else:
            user.password_hash = hash_password(body.new_password)
            user.must_change_password = False
            user.updated_at = now
            _revoke_all(db, user.id)
            tokens = _issue_tokens(db, user, request, now)
            log(db, actor=actor, org_id=user.org_id, action="auth.password_changed",
                entity_type="user", entity_id=user.id, ip=client_ip(request),
                description=f"{user.full_name} сменил пароль")
    if error:
        raise HTTPException(400, error)
    return tokens
