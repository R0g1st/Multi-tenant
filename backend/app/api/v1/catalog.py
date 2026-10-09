"""Подразделения и должности: одинаковая логика, два набора эндпоинтов."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.deps import Actor, get_db, require_org, require_roles, resolve_org
from app.models import Department, Employee, Position
from app.schemas import CatalogIn, CatalogOut, CatalogUpdate
from app.services.audit import client_ip, log

VIEWERS = ("superadmin", "center_admin", "org_admin")
EDITORS = ("superadmin", "center_admin", "org_admin")


def build_router(model, prefix: str, entity: str, label: str, employee_col: str) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[prefix.strip("/")])

    def get_item(db, item_id: UUID):
        obj = db.get(model, item_id)
        if obj is None or obj.deleted_at is not None:
            raise HTTPException(404, f"Запись не найдена ({label})")
        return obj

    @router.get("", response_model=list[CatalogOut])
    def list_items(org_id: UUID | None = None,
                   actor: Actor = Depends(require_roles(*VIEWERS)), db=Depends(get_db)):
        conds = [model.deleted_at.is_(None)]
        if org_id:
            conds.append(model.org_id == org_id)
        return db.scalars(select(model).where(*conds).order_by(model.name)).all()

    @router.post("", response_model=CatalogOut, status_code=201)
    def create_item(body: CatalogIn, request: Request,
                    actor: Actor = Depends(require_roles(*EDITORS)), db=Depends(get_db)):
        org_id = resolve_org(actor, body.org_id)
        require_org(db, org_id)
        obj = model(org_id=org_id, name=body.name.strip())
        db.add(obj)
        try:
            db.flush()
        except IntegrityError:
            raise HTTPException(409, f"Такое значение уже существует ({label})")
        log(db, actor=actor, org_id=org_id, action=f"{entity}.create", entity_type=entity,
            entity_id=obj.id, ip=client_ip(request),
            description=f"{actor.full_name} создал {label} «{obj.name}»")
        return obj

    @router.patch("/{item_id}", response_model=CatalogOut)
    def rename_item(item_id: UUID, body: CatalogUpdate, request: Request,
                    actor: Actor = Depends(require_roles(*EDITORS)), db=Depends(get_db)):
        obj = get_item(db, item_id)
        old = obj.name
        obj.name = body.name.strip()
        try:
            db.flush()
        except IntegrityError:
            raise HTTPException(409, f"Такое значение уже существует ({label})")
        log(db, actor=actor, org_id=obj.org_id, action=f"{entity}.update", entity_type=entity,
            entity_id=obj.id, details={"name": [old, obj.name]}, ip=client_ip(request),
            description=f"{actor.full_name} переименовал {label} «{old}» в «{obj.name}»")
        return obj

    @router.delete("/{item_id}", status_code=204)
    def delete_item(item_id: UUID, request: Request,
                    actor: Actor = Depends(require_roles(*EDITORS)), db=Depends(get_db)):
        obj = get_item(db, item_id)
        obj.deleted_at = datetime.now(timezone.utc)
        db.execute(update(Employee).where(getattr(Employee, employee_col) == obj.id)
                   .values({employee_col: None}))
        log(db, actor=actor, org_id=obj.org_id, action=f"{entity}.delete", entity_type=entity,
            entity_id=obj.id, ip=client_ip(request),
            description=f"{actor.full_name} удалил {label} «{obj.name}»")

    return router


departments_router = build_router(Department, "/departments", "department", "подразделение", "department_id")
positions_router = build_router(Position, "/positions", "position", "должность", "position_id")
