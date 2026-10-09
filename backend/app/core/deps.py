"""Зависимости FastAPI: текущий пользователь, роли, сессия БД с контекстом организации."""
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import tenant_session
from app.core.tokens import decode_access_token
from app.models import Organization, User

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Actor:
    id: UUID
    role: str
    org_id: UUID | None
    full_name: str
    phone: str
    must_change_password: bool

    @property
    def is_center_wide(self) -> bool:
        """Видит все организации: сотрудники учебного центра."""
        return self.role in ("superadmin", "center_admin") or (
            self.role == "ohs_engineer" and self.org_id is None)


def _unauthorized() -> HTTPException:
    return HTTPException(401, "Требуется авторизация", headers={"WWW-Authenticate": "Bearer"})


def org_is_usable(db: Session, user: User) -> bool:
    if user.org_id is None:
        return True
    org = db.get(Organization, user.org_id)
    return bool(org and org.deleted_at is None and org.status == "active")


def current_actor(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Actor:
    """Пользователь по токену. Актуальные роль/статус берутся из БД на каждый запрос,
    поэтому деактивация и смена роли действуют немедленно."""
    if creds is None:
        raise _unauthorized()
    try:
        user_id = UUID(decode_access_token(creds.credentials)["sub"])
    except (jwt.PyJWTError, ValueError):
        raise _unauthorized()
    with tenant_session(bypass=True) as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active or not org_is_usable(db, user):
            raise _unauthorized()
        return Actor(user.id, user.role, user.org_id, user.full_name, user.phone,
                     user.must_change_password)


def authed_actor(actor: Actor = Depends(current_actor)) -> Actor:
    if actor.must_change_password:
        raise HTTPException(403, {"code": "password_change_required",
                                  "message": "Необходимо сменить временный пароль"})
    return actor


def require_roles(*roles: str):
    def dependency(actor: Actor = Depends(authed_actor)) -> Actor:
        if actor.role not in roles:
            raise HTTPException(403, "Недостаточно прав для выполнения действия")
        return actor
    return dependency


def get_db(actor: Actor = Depends(authed_actor)) -> Iterator[Session]:
    """Сессия БД: контекст организации задаётся здесь, из БД-пользователя, а не из запроса."""
    with tenant_session(org_id=actor.org_id, bypass=actor.is_center_wide) as db:
        yield db


def resolve_org(actor: Actor, supplied: UUID | None) -> UUID:
    """Организация для создаваемой записи. Пользователь организации не может выбрать чужую."""
    if actor.org_id is not None:
        if supplied is not None and supplied != actor.org_id:
            raise HTTPException(403, "Нельзя работать с другой организацией")
        return actor.org_id
    if supplied is None:
        raise HTTPException(422, "Укажите организацию")
    return supplied


def require_org(db: Session, org_id: UUID) -> Organization:
    org = db.get(Organization, org_id)
    if org is None or org.deleted_at is not None:
        raise HTTPException(404, "Организация не найдена")
    if org.status != "active":
        raise HTTPException(409, "Организация заблокирована")
    return org
