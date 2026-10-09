from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.deps import Actor, get_db, require_roles
from app.models import AuditLog
from app.schemas import AuditOut, Page

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditOut])
def list_audit(org_id: UUID | None = None, actor_user_id: UUID | None = None,
               action: str | None = None, entity_type: str | None = None,
               date_from: datetime | None = None, date_to: datetime | None = None,
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               actor: Actor = Depends(require_roles("superadmin", "center_admin")), db=Depends(get_db)):
    conds = []
    if org_id:
        conds.append(AuditLog.org_id == org_id)
    if actor_user_id:
        conds.append(AuditLog.actor_user_id == actor_user_id)
    if action:
        conds.append(AuditLog.action == action)
    if entity_type:
        conds.append(AuditLog.entity_type == entity_type)
    if date_from:
        conds.append(AuditLog.at >= date_from)
    if date_to:
        conds.append(AuditLog.at <= date_to)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conds))
    items = db.scalars(select(AuditLog).where(*conds).order_by(AuditLog.at.desc(), AuditLog.id.desc())
                       .limit(limit).offset(offset)).all()
    return Page(items=[AuditOut.model_validate(i) for i in items], total=total)
