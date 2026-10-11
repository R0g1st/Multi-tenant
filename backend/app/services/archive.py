"""Архив «Прервано или закрыто».

Отключённый сотрудник виден только главному администратору, а через ARCHIVE_AFTER после
отключения удаляется из рабочих таблиц (вместе со входом и обучением). Перед удалением всё,
что о нём известно, сохраняется в employee_archive.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.db import tenant_session
from app.models import (Assignment, Course, Department, Employee, EmployeeArchive, Organization,
                        Position, User)
from app.services.audit import log

ARCHIVE_AFTER = timedelta(days=7)
logger = logging.getLogger("uvicorn.error")


def archive_at(e: Employee) -> datetime | None:
    """Когда отключённый сотрудник уйдёт в архив."""
    return e.deactivated_at + ARCHIVE_AFTER if e.status == "inactive" and e.deactivated_at else None


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _snapshot(db, e: Employee) -> EmployeeArchive:
    org = db.get(Organization, e.org_id)
    dept = db.get(Department, e.department_id) if e.department_id else None
    pos = db.get(Position, e.position_id) if e.position_id else None
    user = db.get(User, e.user_id) if e.user_id else None
    courses = db.execute(select(Assignment, Course.title).join(Course, Course.id == Assignment.course_id)
                         .where(Assignment.employee_id == e.id).order_by(Assignment.assigned_at)).all()
    data = {
        "employee": {
            "full_name": e.full_name, "birth_date": _iso(e.birth_date), "phone": e.phone, "email": e.email,
            "hired_at": _iso(e.hired_at), "created_at": _iso(e.created_at),
            "deactivated_at": _iso(e.deactivated_at),
        },
        "login": {
            "phone": user.phone, "role": user.role, "created_at": _iso(user.created_at),
            "last_login_at": _iso(user.last_login_at),
        } if user else None,
        "training": [{
            "course": title, "assigned_at": _iso(a.assigned_at), "status": a.status, "score": a.score,
            "attempts": a.attempts, "completed_at": _iso(a.completed_at), "expires_at": _iso(a.expires_at),
            "cancelled_at": _iso(a.cancelled_at),
        } for a, title in courses],
    }
    return EmployeeArchive(
        id=e.id, org_id=e.org_id, org_name=org.name if org else None, full_name=e.full_name,
        position_name=pos.name if pos else None, department_name=dept.name if dept else None,
        phone=e.phone or (user.phone if user else None), deactivated_at=e.deactivated_at, data=data)


def archive_expired(org_ids: list | None = None) -> int:
    """Переносит в архив сотрудников, отключённых больше ARCHIVE_AFTER назад. Возвращает их число.
    org_ids — только эти заказчики (для тестов)."""
    border = datetime.now(timezone.utc) - ARCHIVE_AFTER
    conds = [Employee.status == "inactive", Employee.deactivated_at <= border]
    if org_ids is not None:
        conds.append(Employee.org_id.in_(org_ids))
    with tenant_session(bypass=True) as db:
        expired = db.scalars(select(Employee).where(*conds).with_for_update(skip_locked=True)).all()
        for e in expired:
            db.add(_snapshot(db, e))
            user_id = e.user_id
            log(db, actor=None, org_id=e.org_id, action="employee.archive", entity_type="employee",
                entity_id=e.id, description=f"Сотрудник «{e.full_name}» перенесён в архив "
                                            f"«Прервано или закрыто» (отключён 7 дней назад)")
            db.flush()
            # назначения и попытки тестов удаляются каскадом (миграция 0007)
            db.execute(delete(Employee).where(Employee.id == e.id))
            if user_id:
                db.execute(delete(User).where(User.id == user_id, User.role == "employee"))
        return len(expired)


def run_safely() -> None:
    try:
        count = archive_expired()
        if count:
            logger.info("В архив «Прервано или закрыто» перенесено сотрудников: %s", count)
    except Exception:  # фоновая задача не должна ронять сервер
        logger.exception("Не удалось перенести отключённых сотрудников в архив")
