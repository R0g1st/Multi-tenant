"""Архив «Прервано или закрыто»: сотрудники, удалённые через неделю после отключения.
Только главный администратор."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.core.deps import Actor, get_db, require_roles
from app.models import EmployeeArchive

router = APIRouter(prefix="/archive", tags=["archive"])


class ArchiveOut(BaseModel):
    id: UUID
    org_name: str | None
    full_name: str
    position_name: str | None
    department_name: str | None
    phone: str | None
    deactivated_at: datetime | None
    archived_at: datetime
    data: dict


class ArchivePage(BaseModel):
    items: list[ArchiveOut]
    total: int


@router.get("", response_model=ArchivePage)
def list_archive(q: str | None = Query(None, max_length=200),
                 limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                 actor: Actor = Depends(require_roles("superadmin")), db=Depends(get_db)):
    conds = []
    if q:
        conds.append(or_(EmployeeArchive.full_name.icontains(q, autoescape=True),
                         EmployeeArchive.org_name.icontains(q, autoescape=True),
                         EmployeeArchive.phone.icontains(q, autoescape=True)))
    total = db.scalar(select(func.count()).select_from(EmployeeArchive).where(*conds))
    rows = db.scalars(select(EmployeeArchive).where(*conds).order_by(EmployeeArchive.archived_at.desc())
                      .limit(limit).offset(offset)).all()
    return ArchivePage(items=[ArchiveOut.model_validate(r, from_attributes=True) for r in rows], total=total)
