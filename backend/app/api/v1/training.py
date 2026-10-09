"""Назначение обучения и его прохождение.

/assignments — назначают и смотрят результаты: учебный центр (все заказчики) и заказчик (только
свои работники, это обеспечивает RLS). /my — работник проходит назначенные ему курсы.
"""
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.v1.courses import get_course
from app.core.deps import Actor, get_db, require_roles
from app.core.tokens import create_file_token
from app.models import Assignment, Course, Department, Employee, Organization, TestAttempt
from app.schemas import (AssignIn, AssignmentOut, AssignmentState, AssignResultOut, FileLinkOut,
                         MyCourseOut, MyMaterialOut, PublicQuestion, TestResultOut, TestSubmitIn)
from app.services.audit import client_ip, log
from app.services.training import complete, course_materials, grade, materials_map, state, viewed_count

router = APIRouter(tags=["training"])
SUPERVISORS = require_roles("superadmin", "center_admin", "org_admin")
WORKER = require_roles("employee")


def _rows(db, *conds):
    stmt = (select(Assignment, Employee.full_name, Department.name, Course.title, Course.test,
                   Organization.name)
            .join(Employee, Employee.id == Assignment.employee_id)
            .outerjoin(Department, Department.id == Employee.department_id)
            .join(Course, Course.id == Assignment.course_id)
            .join(Organization, Organization.id == Assignment.org_id)
            .where(Assignment.cancelled_at.is_(None), *conds)
            .order_by(Assignment.assigned_at.desc()))
    rows = db.execute(stmt).all()
    mats = materials_map({r[0].course_id for r in rows})
    return [_out(*r, mats[r[0].course_id]) for r in rows]


def _out(a: Assignment, emp_name, dept, title, test, org_name, mats) -> AssignmentOut:
    return AssignmentOut(
        id=a.id, org_id=a.org_id, org_name=org_name, employee_id=a.employee_id, employee_name=emp_name,
        department_name=dept, course_id=a.course_id, course_title=title, assigned_at=a.assigned_at,
        due_date=a.due_date, state=state(a), viewed=viewed_count(a, mats), materials=len(mats),
        has_test=bool(test), attempts=a.attempts, score=a.score, completed_at=a.completed_at,
        expires_at=a.expires_at)


# ---------- Назначения (центр и заказчик) ----------
@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(org_id: UUID | None = None, course_id: UUID | None = None,
                     employee_id: UUID | None = None, state_: AssignmentState | None = Query(None, alias="state"),
                     q: str | None = Query(None, max_length=200),
                     actor: Actor = Depends(SUPERVISORS), db=Depends(get_db)):
    conds = []
    if org_id:
        conds.append(Assignment.org_id == org_id)
    if course_id:
        conds.append(Assignment.course_id == course_id)
    if employee_id:
        conds.append(Assignment.employee_id == employee_id)
    if q:
        conds.append(Employee.full_name.ilike(f"%{q}%", autoescape=True))
    items = _rows(db, *conds)
    return [i for i in items if i.state == state_] if state_ else items


@router.post("/assignments", response_model=AssignResultOut, status_code=201)
def assign(body: AssignIn, request: Request, actor: Actor = Depends(SUPERVISORS), db=Depends(get_db)):
    course = get_course(db, body.course_id)
    if not course.test and not course_materials(course.id):
        raise HTTPException(422, "В курсе нет ни материалов, ни теста — назначать нечего")
    if body.due_date and body.due_date < date.today():
        raise HTTPException(422, "Срок прохождения уже прошёл")
    created, skipped = 0, []
    for emp_id in dict.fromkeys(body.employee_ids):
        emp = db.get(Employee, emp_id)  # RLS: заказчик не получит чужого работника
        if emp is None or emp.deleted_at is not None:
            raise HTTPException(404, "Сотрудник не найден")
        if emp.status != "active":
            skipped.append(f"{emp.full_name} (деактивирован)")
            continue
        if course.org_id is not None and emp.org_id != course.org_id:
            skipped.append(f"{emp.full_name} (это курс другого заказчика)")
            continue
        try:
            with db.begin_nested():
                db.add(Assignment(org_id=emp.org_id, course_id=course.id, employee_id=emp.id,
                                  assigned_by=actor.id, due_date=body.due_date))
        except IntegrityError:
            skipped.append(f"{emp.full_name} (курс уже назначен и не пройден)")
            continue
        created += 1
        log(db, actor=actor, org_id=emp.org_id, action="training.assign", entity_type="employee",
            entity_id=emp.id, ip=client_ip(request),
            details={"course": course.title, "due_date": str(body.due_date) if body.due_date else None},
            description=f"{actor.full_name} назначил курс «{course.title}» сотруднику {emp.full_name}")
    return AssignResultOut(created=created, skipped=skipped)


@router.delete("/assignments/{assignment_id}", status_code=204)
def cancel_assignment(assignment_id: UUID, request: Request,
                      actor: Actor = Depends(SUPERVISORS), db=Depends(get_db)):
    a = db.get(Assignment, assignment_id)
    if a is None or a.cancelled_at is not None:
        raise HTTPException(404, "Назначение не найдено")
    a.cancelled_at = datetime.now(timezone.utc)
    emp, course = db.get(Employee, a.employee_id), db.get(Course, a.course_id)
    log(db, actor=actor, org_id=a.org_id, action="training.cancel", entity_type="employee",
        entity_id=a.employee_id, ip=client_ip(request),
        description=f"{actor.full_name} отменил курс «{course.title}» у сотрудника {emp.full_name}")


# ---------- Моё обучение (работник) ----------
def _me(db, actor: Actor) -> Employee:
    emp = db.scalar(select(Employee).where(Employee.user_id == actor.id, Employee.deleted_at.is_(None)))
    if emp is None:
        raise HTTPException(404, "Вы не числитесь сотрудником организации")
    return emp


def _my_assignment(db, actor: Actor, assignment_id: UUID) -> tuple[Assignment, Course]:
    a = db.get(Assignment, assignment_id)
    if a is None or a.cancelled_at is not None or a.employee_id != _me(db, actor).id:
        raise HTTPException(404, "Курс не найден")
    return a, db.get(Course, a.course_id)


@router.get("/my/assignments", response_model=list[AssignmentOut])
def my_assignments(actor: Actor = Depends(WORKER), db=Depends(get_db)):
    return _rows(db, Assignment.employee_id == _me(db, actor).id)


@router.get("/my/assignments/{assignment_id}", response_model=MyCourseOut)
def my_course(assignment_id: UUID, actor: Actor = Depends(WORKER), db=Depends(get_db)):
    a, course = _my_assignment(db, actor, assignment_id)
    items = course_materials(course.id)
    seen = set(a.viewed)
    out = _rows(db, Assignment.id == a.id)[0]
    return MyCourseOut(
        assignment=out, description=course.description, pass_score=course.pass_score,
        materials=[MyMaterialOut(item_id=i.id, title=i.title, description=i.description, kind=i.kind,
                                 viewed=str(i.id) in seen) for i in items],
        test=[PublicQuestion(text=q["text"], multiple=q["multiple"], options=[o["text"] for o in q["options"]])
              for q in course.test],
        can_take_test=bool(course.test) and a.status != "passed" and out.viewed == out.materials)


@router.post("/my/assignments/{assignment_id}/materials/{item_id}", response_model=FileLinkOut)
def open_material(assignment_id: UUID, item_id: UUID, request: Request,
                  actor: Actor = Depends(WORKER), db=Depends(get_db)):
    """Ссылка на материал курса; заодно отмечает, что работник его открыл."""
    a, course = _my_assignment(db, actor, assignment_id)
    ids = [i.id for i in course_materials(course.id)]
    if item_id not in ids:
        raise HTTPException(404, "Материал не найден в этом курсе")
    if str(item_id) not in a.viewed:
        a.viewed = [*a.viewed, str(item_id)]
        if a.status == "assigned":
            a.status = "in_progress"
        if a.status != "passed" and not course.test and viewed_count(a, ids) == len(ids):
            complete(a, course, None)
            log(db, actor=actor, org_id=a.org_id, action="training.passed", entity_type="employee",
                entity_id=a.employee_id, ip=client_ip(request),
                description=f"{actor.full_name} прошёл курс «{course.title}» (изучены все материалы)")
    return FileLinkOut(url=f"/api/v1/library/files/{item_id}?t={create_file_token(item_id)}")


@router.post("/my/assignments/{assignment_id}/test", response_model=TestResultOut)
def submit_test(assignment_id: UUID, body: TestSubmitIn, request: Request,
                actor: Actor = Depends(WORKER), db=Depends(get_db)):
    a, course = _my_assignment(db, actor, assignment_id)
    if not course.test:
        raise HTTPException(409, "В этом курсе нет теста")
    if a.status == "passed":
        raise HTTPException(409, "Курс уже пройден")
    ids = [i.id for i in course_materials(course.id)]
    if viewed_count(a, ids) < len(ids):
        raise HTTPException(409, "Сначала изучите все материалы курса")
    if len(body.answers) != len(course.test):
        raise HTTPException(422, "Ответьте на все вопросы теста")
    for q, chosen in zip(course.test, body.answers):
        if any(i < 0 or i >= len(q["options"]) for i in chosen):
            raise HTTPException(422, "Неверный вариант ответа")
        if not q["multiple"] and len(set(chosen)) != 1:
            raise HTTPException(422, f"В вопросе «{q['text'][:60]}» нужно выбрать один ответ")
    correct, score, protocol = grade(course.test, body.answers)
    passed = score >= course.pass_score
    db.add(TestAttempt(org_id=a.org_id, assignment_id=a.id, score=score, passed=passed, answers=protocol))
    a.attempts += 1
    a.score = max(a.score or 0, score)
    if a.status == "assigned":
        a.status = "in_progress"
    if passed:
        complete(a, course, score)
    log(db, actor=actor, org_id=a.org_id, action="training.passed" if passed else "training.failed",
        entity_type="employee", entity_id=a.employee_id, ip=client_ip(request),
        details={"course": course.title, "score": score, "attempt": a.attempts},
        description=f"{actor.full_name} {'сдал' if passed else 'не сдал'} тест курса «{course.title}»: "
                    f"{score}% (попытка {a.attempts})")
    return TestResultOut(score=score, passed=passed, correct=correct, total=len(course.test),
                         pass_score=course.pass_score)
