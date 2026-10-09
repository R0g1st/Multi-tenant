from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import Actor, get_db, require_roles
from app.models import Organization, User
from app.schemas import (CustomerContact, MyCustomerOut, OrganizationIn, OrganizationOut,
                         OrganizationUpdate, Page)
from app.services.audit import client_ip, log

router = APIRouter(prefix="/organizations", tags=["organizations"])
VIEWERS = ("superadmin", "center_admin", "org_admin")
CENTER = ("superadmin", "center_admin")


def _get(db, org_id: UUID) -> Organization:
    org = db.get(Organization, org_id)  # RLS: чужую организацию пользователь организации не увидит
    if org is None or org.deleted_at is not None:
        raise HTTPException(404, "Организация не найдена")
    return org


@router.get("", response_model=Page[OrganizationOut])
def list_organizations(q: str | None = None, status: str | None = None,
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                       actor: Actor = Depends(require_roles(*VIEWERS)), db=Depends(get_db)):
    conds = [Organization.deleted_at.is_(None)]
    if q:
        conds.append(or_(Organization.name.ilike(f"%{q}%", autoescape=True),
                         Organization.inn.ilike(f"%{q}%", autoescape=True)))
    if status:
        conds.append(Organization.status == status)
    total = db.scalar(select(func.count()).select_from(Organization).where(*conds))
    items = db.scalars(select(Organization).where(*conds).order_by(Organization.name)
                       .limit(limit).offset(offset)).all()
    return Page(items=[OrganizationOut.model_validate(i) for i in items], total=total)


@router.post("", response_model=OrganizationOut, status_code=201)
def create_organization(body: OrganizationIn, request: Request,
                        actor: Actor = Depends(require_roles(*CENTER)), db=Depends(get_db)):
    org = Organization(**body.model_dump())
    db.add(org)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "Организация с таким ИНН уже существует")
    log(db, actor=actor, org_id=org.id, action="organization.create", entity_type="organization",
        entity_id=org.id, ip=client_ip(request),
        description=f"{actor.full_name} создал организацию «{org.name}»")
    return org


@router.get("/mine", response_model=MyCustomerOut)
def my_customer(actor: Actor = Depends(require_roles("employee", "org_admin")), db=Depends(get_db)):
    """Организация-заказчик текущего пользователя и её представители (контакты для связи)."""
    org = _get(db, actor.org_id)
    reps = db.scalars(select(User).where(User.org_id == org.id, User.role == "org_admin", User.is_active)
                      .order_by(User.full_name)).all()
    return MyCustomerOut(name=org.name, inn=org.inn, kpp=org.kpp, legal_address=org.legal_address,
                         contact_phone=org.contact_phone, contact_email=org.contact_email,
                         responsible_name=org.responsible_name,
                         contacts=[CustomerContact(full_name=u.full_name, phone=u.phone) for u in reps])


@router.get("/{org_id}", response_model=OrganizationOut)
def get_organization(org_id: UUID, actor: Actor = Depends(require_roles(*VIEWERS)), db=Depends(get_db)):
    return _get(db, org_id)


@router.patch("/{org_id}", response_model=OrganizationOut)
def update_organization(org_id: UUID, body: OrganizationUpdate, request: Request,
                        actor: Actor = Depends(require_roles(*CENTER)), db=Depends(get_db)):
    org = _get(db, org_id)
    changes = {}
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None and key in ("name", "status"):
            continue
        old = getattr(org, key)
        if old != value:
            changes[key] = [old, value]
            setattr(org, key, value)
    if changes:
        org.updated_at = datetime.now(timezone.utc)
        try:
            db.flush()
        except IntegrityError:
            raise HTTPException(409, "Организация с таким ИНН уже существует")
        log(db, actor=actor, org_id=org.id, action="organization.update", entity_type="organization",
            entity_id=org.id, details=changes, ip=client_ip(request),
            description=f"{actor.full_name} изменил данные организации «{org.name}»")
    return org


@router.delete("/{org_id}", status_code=204)
def delete_organization(org_id: UUID, request: Request,
                        actor: Actor = Depends(require_roles(*CENTER)), db=Depends(get_db)):
    """Мягкое удаление: данные сохраняются, вход пользователей организации блокируется."""
    org = _get(db, org_id)
    org.deleted_at = datetime.now(timezone.utc)
    log(db, actor=actor, org_id=org.id, action="organization.delete", entity_type="organization",
        entity_id=org.id, ip=client_ip(request),
        description=f"{actor.full_name} удалил организацию «{org.name}»")
