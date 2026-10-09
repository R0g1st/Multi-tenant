"""Курсы: набор материалов из библиотеки + тест.

Общие курсы (org_id = None) ведёт учебный центр, их видят и назначают все заказчики.
Заказчик создаёт и свои курсы — из общих материалов и своих; другим заказчикам они не видны."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from app.core.deps import Actor, can_manage, get_db, require_manage, require_roles
from app.models import Assignment, Course, CourseMaterial, LibraryItem, Organization
from app.schemas import (CourseDetailOut, CourseIn, CourseMaterialOut, CourseMaterialsIn, CourseOut,
                         CourseTestIn, CourseUpdate)
from app.services.audit import client_ip, log
from app.services.training import course_materials

router = APIRouter(prefix="/courses", tags=["courses"])
USERS = require_roles("superadmin", "center_admin", "org_admin")


def get_course(db, course_id: UUID) -> Course:
    c = db.get(Course, course_id)
    if c is None or c.deleted_at is not None:
        raise HTTPException(404, "Курс не найден")
    return c


def _out(c: Course, materials: int, org_name: str | None, actor: Actor) -> CourseOut:
    return CourseOut(id=c.id, org_id=c.org_id, org_name=org_name, editable=can_manage(actor, c.org_id),
                     title=c.title, description=c.description, pass_score=c.pass_score,
                     validity_months=c.validity_months, materials=materials, questions=len(c.test))


def _detail(c: Course, db, actor: Actor) -> CourseDetailOut:
    return CourseDetailOut(
        id=c.id, org_id=c.org_id, editable=can_manage(actor, c.org_id), title=c.title,
        description=c.description, pass_score=c.pass_score,
        validity_months=c.validity_months, test=c.test,
        materials=[CourseMaterialOut(item_id=i.id, title=i.title, kind=i.kind, file_name=i.file_name,
                                     size=i.size) for i in course_materials(c.id, db)])


@router.get("", response_model=list[CourseOut])
def list_courses(actor: Actor = Depends(USERS), db=Depends(get_db)):
    """Учебный центр видит все курсы, заказчик — общие и свои (RLS)."""
    rows = db.execute(select(Course, Organization.name)
                      .outerjoin(Organization, Organization.id == Course.org_id)
                      .where(Course.deleted_at.is_(None))
                      .order_by(Course.org_id.is_not(None), func.lower(Course.title))).all()
    return [_out(c, len(course_materials(c.id, db)), org, actor) for c, org in rows]


@router.post("", response_model=CourseDetailOut, status_code=201)
def create_course(body: CourseIn, request: Request, actor: Actor = Depends(USERS), db=Depends(get_db)):
    # учебный центр создаёт общие курсы, заказчик — свои
    c = Course(**body.model_dump(), test=[], org_id=None if actor.is_center_wide else actor.org_id)
    c.title = c.title.strip()
    db.add(c)
    db.flush()
    log(db, actor=actor, org_id=c.org_id, action="course.create", entity_type="course", entity_id=c.id,
        ip=client_ip(request), description=f"{actor.full_name} создал курс «{c.title}»")
    return _detail(c, db, actor)


@router.get("/{course_id}", response_model=CourseDetailOut)
def get_course_detail(course_id: UUID, actor: Actor = Depends(USERS), db=Depends(get_db)):
    return _detail(get_course(db, course_id), db, actor)


@router.patch("/{course_id}", response_model=CourseDetailOut)
def update_course(course_id: UUID, body: CourseUpdate, request: Request,
                  actor: Actor = Depends(USERS), db=Depends(get_db)):
    c = get_course(db, course_id)
    require_manage(actor, c.org_id)
    data = body.model_dump(exclude_unset=True)
    for key in ("title", "pass_score"):  # обязательные поля null не принимают
        if data.get(key, 0) is None:
            data.pop(key)
    for key, value in data.items():
        setattr(c, key, value.strip() if isinstance(value, str) else value)
    c.updated_at = datetime.now(timezone.utc)
    log(db, actor=actor, org_id=c.org_id, action="course.update", entity_type="course", entity_id=c.id,
        ip=client_ip(request), details={k: str(v) for k, v in data.items()},
        description=f"{actor.full_name} изменил курс «{c.title}»")
    return _detail(c, db, actor)


@router.put("/{course_id}/materials", response_model=CourseDetailOut)
def set_materials(course_id: UUID, body: CourseMaterialsIn, request: Request,
                  actor: Actor = Depends(USERS), db=Depends(get_db)):
    """Задать материалы курса целиком, в нужном порядке."""
    c = get_course(db, course_id)
    require_manage(actor, c.org_id)
    ids = list(dict.fromkeys(body.item_ids))
    found = dict(db.execute(select(LibraryItem.id, LibraryItem.org_id)
                            .where(LibraryItem.id.in_(ids), LibraryItem.deleted_at.is_(None))).all())
    if missing := [i for i in ids if i not in found]:
        raise HTTPException(422, f"Материалы не найдены в библиотеке: {len(missing)}")
    # в общий курс — только общие материалы, иначе файлы заказчика увидят другие заказчики
    if any(org is not None and org != c.org_id for org in found.values()):
        raise HTTPException(422, "В общий курс можно добавлять только материалы общей библиотеки")
    for m in db.scalars(select(CourseMaterial).where(CourseMaterial.course_id == c.id)):
        db.delete(m)
    db.flush()
    db.add_all([CourseMaterial(course_id=c.id, item_id=i, position=n) for n, i in enumerate(ids)])
    c.updated_at = datetime.now(timezone.utc)
    db.flush()
    log(db, actor=actor, org_id=c.org_id, action="course.materials", entity_type="course", entity_id=c.id,
        ip=client_ip(request), details={"count": len(ids)},
        description=f"{actor.full_name} изменил материалы курса «{c.title}» ({len(ids)} шт.)")
    return _detail(c, db, actor)


@router.put("/{course_id}/test", response_model=CourseDetailOut)
def set_test(course_id: UUID, body: CourseTestIn, request: Request,
             actor: Actor = Depends(USERS), db=Depends(get_db)):
    c = get_course(db, course_id)
    require_manage(actor, c.org_id)
    c.test = [q.model_dump() for q in body.questions]
    c.updated_at = datetime.now(timezone.utc)
    log(db, actor=actor, org_id=c.org_id, action="course.test", entity_type="course", entity_id=c.id,
        ip=client_ip(request), details={"questions": len(c.test)},
        description=f"{actor.full_name} изменил тест курса «{c.title}» ({len(c.test)} вопр.)")
    return _detail(c, db, actor)


@router.delete("/{course_id}", status_code=204)
def delete_course(course_id: UUID, request: Request, actor: Actor = Depends(USERS), db=Depends(get_db)):
    c = get_course(db, course_id)
    require_manage(actor, c.org_id)
    open_ = db.scalar(select(func.count()).select_from(Assignment).where(
        Assignment.course_id == c.id, Assignment.cancelled_at.is_(None), Assignment.status != "passed"))
    if open_:
        raise HTTPException(409, f"Курс сейчас проходят ({open_} назначений). Сначала отмените их.")
    c.deleted_at = datetime.now(timezone.utc)
    log(db, actor=actor, org_id=c.org_id, action="course.delete", entity_type="course", entity_id=c.id,
        ip=client_ip(request), description=f"{actor.full_name} удалил курс «{c.title}»")
