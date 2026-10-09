"""Общая логика обучения: материалы курса, состояние назначения, проверка теста."""
import calendar
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.db import tenant_session
from app.models import Assignment, Course, CourseMaterial, LibraryItem


def course_materials(course_id: UUID, db=None) -> list[LibraryItem]:
    """Материалы курса по порядку (удалённые из библиотеки пропускаются).
    Библиотека закрыта RLS для всех, кроме учебного центра, поэтому читаем её отдельной
    служебной сессией — вызывающий код обязан сам проверить право на курс."""
    stmt = (select(LibraryItem).join(CourseMaterial, CourseMaterial.item_id == LibraryItem.id)
            .where(CourseMaterial.course_id == course_id, LibraryItem.deleted_at.is_(None))
            .order_by(CourseMaterial.position))
    if db is not None:  # сессия учебного центра: видит и ещё не сохранённые изменения запроса
        return list(db.scalars(stmt))
    with tenant_session(bypass=True) as own:
        return list(own.scalars(stmt))


def materials_map(course_ids) -> dict[UUID, list[UUID]]:
    """{курс: [id материалов]} одним запросом — для списков назначений."""
    out: dict[UUID, list[UUID]] = {c: [] for c in course_ids}
    if not out:
        return out
    with tenant_session(bypass=True) as db:
        rows = db.execute(
            select(CourseMaterial.course_id, CourseMaterial.item_id)
            .join(LibraryItem, LibraryItem.id == CourseMaterial.item_id)
            .where(CourseMaterial.course_id.in_(list(out)), LibraryItem.deleted_at.is_(None))
            .order_by(CourseMaterial.position)).all()
    for course_id, item_id in rows:
        out[course_id].append(item_id)
    return out


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def state(a: Assignment, today: date | None = None) -> str:
    """Что показывать людям: назначен / в процессе / пройден / просрочен / истёк срок действия."""
    today = today or date.today()
    if a.status == "passed":
        return "expired" if a.expires_at and a.expires_at < today else "passed"
    if a.due_date and a.due_date < today:
        return "overdue"
    return a.status


def viewed_count(a: Assignment, material_ids: list[UUID]) -> int:
    seen = set(a.viewed)
    return sum(str(i) in seen for i in material_ids)


def complete(a: Assignment, course: Course, score: int | None) -> None:
    now = datetime.now(timezone.utc)
    a.status = "passed"
    a.completed_at = now
    if score is not None:
        a.score = score
    a.expires_at = add_months(now.date(), course.validity_months) if course.validity_months else None


def grade(test: list[dict], answers: list[list[int]]) -> tuple[int, int, list[dict]]:
    """(верных ответов, % результата, протокол ответов). Вопрос засчитывается, только если
    выбраны ровно все правильные варианты."""
    correct, protocol = 0, []
    for n, q in enumerate(test):
        chosen = sorted(set(answers[n])) if n < len(answers) else []
        right = sorted(i for i, o in enumerate(q["options"]) if o["correct"])
        ok = chosen == right
        correct += ok
        protocol.append({"question": q["text"], "chosen": [q["options"][i]["text"] for i in chosen],
                         "correct": ok})
    total = len(test)
    return correct, round(correct * 100 / total) if total else 100, protocol
