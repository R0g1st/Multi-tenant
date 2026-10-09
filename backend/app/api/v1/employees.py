from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.deps import Actor, get_db, require_org, require_roles, resolve_org
from app.core.security import generate_temp_password, hash_password
from app.models import Department, Employee, Position, RefreshSession, User
from app.schemas import (CredentialsOut, EmployeeIn, EmployeeOut, EmployeeUpdate,
                         GrantAccessIn, Page)
from app.services.audit import client_ip, log

router = APIRouter(prefix="/employees", tags=["employees"])
VIEWERS = ("superadmin", "center_admin", "ohs_engineer", "org_admin")
ADMINS = ("superadmin", "center_admin", "org_admin")


def _select():
    return (select(Employee, Department.name, Position.name, User.is_active)
            .outerjoin(Department, Department.id == Employee.department_id)
            .outerjoin(Position, Position.id == Employee.position_id)
            .outerjoin(User, User.id == Employee.user_id))


def _out(row) -> EmployeeOut:
    e, dept, pos, user_active = row
    return EmployeeOut(
        id=e.id, org_id=e.org_id, full_name=e.full_name, birth_date=e.birth_date,
        department_id=e.department_id, department_name=dept,
        position_id=e.position_id, position_name=pos,
        phone=e.phone, email=e.email, hired_at=e.hired_at, status=e.status,
        has_access=bool(user_active))


def _entity(db, employee_id: UUID) -> Employee:
    e = db.get(Employee, employee_id)  # RLS скрывает сотрудников чужих организаций
    if e is None or e.deleted_at is not None:
        raise HTTPException(404, "Сотрудник не найден")
    return e


def _view(db, employee_id: UUID) -> EmployeeOut:
    row = db.execute(_select().where(Employee.id == employee_id)).first()
    return _out(row)


def _check_refs(db, org_id: UUID, department_id: UUID | None, position_id: UUID | None) -> None:
    """Подразделение и должность должны принадлежать той же организации (важно для сотрудников центра,
    у которых RLS не ограничивает выборку)."""
    if department_id:
        d = db.get(Department, department_id)
        if d is None or d.deleted_at is not None or d.org_id != org_id:
            raise HTTPException(422, "Подразделение не найдено в этой организации")
    if position_id:
        p = db.get(Position, position_id)
        if p is None or p.deleted_at is not None or p.org_id != org_id:
            raise HTTPException(422, "Должность не найдена в этой организации")


def _revoke_sessions(db, user_id) -> None:
    db.execute(update(RefreshSession)
               .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))


@router.get("", response_model=Page[EmployeeOut])
def list_employees(q: str | None = None, org_id: UUID | None = None,
                   department_id: UUID | None = None, position_id: UUID | None = None,
                   status: Literal["active", "inactive"] | None = None,
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   actor: Actor = Depends(require_roles(*VIEWERS)), db=Depends(get_db)):
    conds = [Employee.deleted_at.is_(None)]
    if q:
        conds.append(Employee.full_name.ilike(f"%{q}%", autoescape=True))
    if org_id:
        conds.append(Employee.org_id == org_id)
    if department_id:
        conds.append(Employee.department_id == department_id)
    if position_id:
        conds.append(Employee.position_id == position_id)
    if status:
        conds.append(Employee.status == status)
    total = db.scalar(select(func.count()).select_from(Employee).where(*conds))
    rows = db.execute(_select().where(*conds).order_by(Employee.full_name)
                      .limit(limit).offset(offset)).all()
    return Page(items=[_out(r) for r in rows], total=total)


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(body: EmployeeIn, request: Request,
                    actor: Actor = Depends(require_roles(*ADMINS)), db=Depends(get_db)):
    org_id = resolve_org(actor, body.org_id)
    require_org(db, org_id)
    _check_refs(db, org_id, body.department_id, body.position_id)
    data = body.model_dump(exclude={"org_id"})
    e = Employee(org_id=org_id, **data)
    db.add(e)
    db.flush()
    log(db, actor=actor, org_id=org_id, action="employee.create", entity_type="employee",
        entity_id=e.id, ip=client_ip(request),
        description=f"{actor.full_name} создал сотрудника «{e.full_name}»")
    return _view(db, e.id)


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: UUID, actor: Actor = Depends(require_roles(*VIEWERS)), db=Depends(get_db)):
    _entity(db, employee_id)
    return _view(db, employee_id)


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: UUID, body: EmployeeUpdate, request: Request,
                    actor: Actor = Depends(require_roles(*ADMINS)), db=Depends(get_db)):
    e = _entity(db, employee_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("full_name") is None:
        data.pop("full_name", None)
    _check_refs(db, e.org_id, data.get("department_id"), data.get("position_id"))
    changes = {}
    for key, value in data.items():
        old = getattr(e, key)
        if old != value:
            changes[key] = [str(old) if old is not None else None, str(value) if value is not None else None]
            setattr(e, key, value)
    if changes:
        e.updated_at = datetime.now(timezone.utc)
        db.flush()
        log(db, actor=actor, org_id=e.org_id, action="employee.update", entity_type="employee",
            entity_id=e.id, details=changes, ip=client_ip(request),
            description=f"{actor.full_name} изменил данные сотрудника «{e.full_name}»")
    return _view(db, e.id)


@router.post("/{employee_id}/deactivate", response_model=EmployeeOut)
def deactivate_employee(employee_id: UUID, request: Request,
                        actor: Actor = Depends(require_roles(*ADMINS)), db=Depends(get_db)):
    e = _entity(db, employee_id)
    e.status = "inactive"
    e.updated_at = datetime.now(timezone.utc)
    if e.user_id:
        user = db.get(User, e.user_id)
        user.is_active = False
        _revoke_sessions(db, user.id)
    log(db, actor=actor, org_id=e.org_id, action="employee.deactivate", entity_type="employee",
        entity_id=e.id, ip=client_ip(request),
        description=f"{actor.full_name} деактивировал сотрудника «{e.full_name}»")
    return _view(db, e.id)


@router.post("/{employee_id}/restore", response_model=EmployeeOut)
def restore_employee(employee_id: UUID, request: Request,
                     actor: Actor = Depends(require_roles(*ADMINS)), db=Depends(get_db)):
    """Возвращает сотрудника в список. Доступ в систему не восстанавливается автоматически:
    его нужно выдать заново кнопкой «Выдать доступ»."""
    e = _entity(db, employee_id)
    e.status = "active"
    e.updated_at = datetime.now(timezone.utc)
    log(db, actor=actor, org_id=e.org_id, action="employee.restore", entity_type="employee",
        entity_id=e.id, ip=client_ip(request),
        description=f"{actor.full_name} восстановил сотрудника «{e.full_name}»")
    return _view(db, e.id)


@router.post("/{employee_id}/grant-access", response_model=CredentialsOut)
def grant_access(employee_id: UUID, request: Request, body: GrantAccessIn | None = None,
                 actor: Actor = Depends(require_roles(*ADMINS)), db=Depends(get_db)):
    """Создаёт (или повторно включает) личный кабинет сотрудника по номеру телефона."""
    e = _entity(db, employee_id)
    if e.status != "active":
        raise HTTPException(409, "Сотрудник деактивирован. Сначала восстановите его.")
    require_org(db, e.org_id)
    temp = generate_temp_password()
    user = db.get(User, e.user_id) if e.user_id else None
    if user is not None:
        if user.is_active:
            raise HTTPException(409, "Доступ уже выдан")
        user.is_active = True
        user.password_hash = hash_password(temp)
        user.must_change_password = True
        user.failed_login_count = 0
        user.locked_until = None
        user.updated_at = datetime.now(timezone.utc)
    else:
        phone = (body.phone if body else None) or e.phone
        if not phone:
            raise HTTPException(422, "Укажите номер телефона сотрудника")
        user = User(org_id=e.org_id, phone=phone, password_hash=hash_password(temp),
                    full_name=e.full_name, role="employee", must_change_password=True)
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            raise HTTPException(409, "Этот номер телефона уже используется в системе")
        e.user_id = user.id
        if not e.phone:
            e.phone = phone
    db.flush()
    log(db, actor=actor, org_id=e.org_id, action="employee.grant_access", entity_type="employee",
        entity_id=e.id, ip=client_ip(request), details={"user_id": str(user.id), "phone": user.phone},
        description=f"{actor.full_name} выдал доступ в систему сотруднику «{e.full_name}»")
    return CredentialsOut(user_id=user.id, phone=user.phone, temporary_password=temp)


@router.post("/{employee_id}/reset-password", response_model=CredentialsOut)
def reset_password(employee_id: UUID, request: Request,
                   actor: Actor = Depends(require_roles(*ADMINS)), db=Depends(get_db)):
    e = _entity(db, employee_id)
    user = db.get(User, e.user_id) if e.user_id else None
    if user is None or not user.is_active:
        raise HTTPException(409, "У сотрудника нет активного доступа")
    temp = generate_temp_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    user.updated_at = datetime.now(timezone.utc)
    _revoke_sessions(db, user.id)
    log(db, actor=actor, org_id=e.org_id, action="employee.reset_password", entity_type="employee",
        entity_id=e.id, ip=client_ip(request),
        description=f"{actor.full_name} сбросил пароль сотруднику «{e.full_name}»")
    return CredentialsOut(user_id=user.id, phone=user.phone, temporary_password=temp)


@router.post("/{employee_id}/revoke-access", response_model=EmployeeOut)
def revoke_access(employee_id: UUID, request: Request,
                  actor: Actor = Depends(require_roles(*ADMINS)), db=Depends(get_db)):
    e = _entity(db, employee_id)
    user = db.get(User, e.user_id) if e.user_id else None
    if user is None or not user.is_active:
        raise HTTPException(409, "У сотрудника нет активного доступа")
    user.is_active = False
    _revoke_sessions(db, user.id)
    log(db, actor=actor, org_id=e.org_id, action="employee.revoke_access", entity_type="employee",
        entity_id=e.id, ip=client_ip(request),
        description=f"{actor.full_name} отозвал доступ в систему у сотрудника «{e.full_name}»")
    return _view(db, e.id)
