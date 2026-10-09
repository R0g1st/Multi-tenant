"""Пользователи руководящих ролей (не сотрудники — тех ведёт модуль employees)."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.deps import Actor, get_db, require_org, require_roles
from app.core.security import generate_temp_password, hash_password
from app.models import RefreshSession, User
from app.schemas import CredentialsOut, Page, Role, UserIn, UserOut, UserUpdate
from app.services.audit import client_ip, log

router = APIRouter(prefix="/users", tags=["users"])
STAFF = ("superadmin", "center_admin")
# Какие роли может создавать и изменять каждая роль
MANAGEABLE = {
    "superadmin": {"superadmin", "center_admin", "org_admin"},
    "center_admin": {"org_admin"},
}


def hidden_roles(actor: Actor) -> tuple[str, ...]:
    """Главного администратора видит только главный администратор."""
    return () if actor.role == "superadmin" else ("superadmin",)


def _target(db, actor: Actor, user_id: UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.role == "employee" or user.role in hidden_roles(actor):
        raise HTTPException(404, "Пользователь не найден")
    if user.role not in MANAGEABLE[actor.role]:
        raise HTTPException(403, "Недостаточно прав для управления этим пользователем")
    return user


def _revoke(db, user_id) -> None:
    db.execute(update(RefreshSession)
               .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))


@router.get("", response_model=Page[UserOut])
def list_users(q: str | None = None, role: Role | None = None, org_id: UUID | None = None,
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               actor: Actor = Depends(require_roles(*STAFF)), db=Depends(get_db)):
    conds = [User.role == role] if role else [User.role != "employee"]
    conds.append(User.role.not_in(hidden_roles(actor)))
    if org_id:
        conds.append(User.org_id == org_id)
    if q:
        conds.append(or_(User.full_name.ilike(f"%{q}%", autoescape=True),
                         User.phone.ilike(f"%{q}%", autoescape=True)))
    total = db.scalar(select(func.count()).select_from(User).where(*conds))
    items = db.scalars(select(User).where(*conds).order_by(User.full_name)
                       .limit(limit).offset(offset)).all()
    return Page(items=[UserOut.model_validate(i) for i in items], total=total)


@router.post("", response_model=CredentialsOut, status_code=201)
def create_user(body: UserIn, request: Request,
                actor: Actor = Depends(require_roles(*STAFF)), db=Depends(get_db)):
    if body.role not in MANAGEABLE[actor.role]:
        raise HTTPException(403, "Недостаточно прав для создания пользователя с такой ролью")
    if body.role in ("superadmin", "center_admin") and body.org_id is not None:
        raise HTTPException(422, "Для этой роли организация не указывается")
    if body.role == "org_admin" and body.org_id is None:
        raise HTTPException(422, "Для администратора организации нужно указать организацию")
    if body.role == "employee":
        raise HTTPException(422, "Сотрудники создаются в разделе «Сотрудники»")
    if body.org_id is not None:
        require_org(db, body.org_id)
    temp = generate_temp_password()
    user = User(org_id=body.org_id, phone=body.phone, password_hash=hash_password(temp),
                full_name=body.full_name.strip(), role=body.role, must_change_password=True)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "Этот номер телефона уже используется в системе")
    log(db, actor=actor, org_id=user.org_id, action="user.create", entity_type="user",
        entity_id=user.id, ip=client_ip(request), details={"role": user.role, "phone": user.phone},
        description=f"{actor.full_name} создал пользователя «{user.full_name}» (роль: {user.role})")
    return CredentialsOut(user_id=user.id, phone=user.phone, temporary_password=temp)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: UUID, body: UserUpdate, request: Request,
                actor: Actor = Depends(require_roles(*STAFF)), db=Depends(get_db)):
    user = _target(db, actor, user_id)
    if body.is_active is False and user.id == actor.id:
        raise HTTPException(400, "Нельзя отключить самого себя")
    changes = {}
    if body.full_name is not None and body.full_name != user.full_name:
        changes["full_name"] = [user.full_name, body.full_name]
        user.full_name = body.full_name.strip()
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = [user.is_active, body.is_active]
        user.is_active = body.is_active
        if not body.is_active:
            _revoke(db, user.id)
    if changes:
        user.updated_at = datetime.now(timezone.utc)
        log(db, actor=actor, org_id=user.org_id, action="user.update", entity_type="user",
            entity_id=user.id, details=changes, ip=client_ip(request),
            description=f"{actor.full_name} изменил пользователя «{user.full_name}»")
    return user


@router.post("/{user_id}/reset-password", response_model=CredentialsOut)
def reset_user_password(user_id: UUID, request: Request,
                        actor: Actor = Depends(require_roles(*STAFF)), db=Depends(get_db)):
    user = _target(db, actor, user_id)
    temp = generate_temp_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    user.updated_at = datetime.now(timezone.utc)
    _revoke(db, user.id)
    log(db, actor=actor, org_id=user.org_id, action="user.reset_password", entity_type="user",
        entity_id=user.id, ip=client_ip(request),
        description=f"{actor.full_name} сбросил пароль пользователю «{user.full_name}»")
    return CredentialsOut(user_id=user.id, phone=user.phone, temporary_password=temp)
