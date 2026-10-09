"""Выгрузка сотрудников в CSV (открывается в Excel) для тех, кто с сайтом не работает.

Запуск:  docker compose exec backend python -m app.scripts.export_employees
Файл появится в папке проекта: storage\\employees_ГГГГ-ММ-ДД.csv

Параметры:
  --inn 7707083893   только одна организация (по ИНН)
  --all              включить деактивированных сотрудников
Пароли и их хеши в выгрузку не попадают.
"""
import argparse
import csv
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import tenant_session
from app.models import Department, Employee, Organization, Position


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inn")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    stmt = (select(Organization.name, Organization.inn, Employee.full_name, Department.name,
                   Position.name, Employee.phone, Employee.hired_at, Employee.status)
            .join(Organization, Organization.id == Employee.org_id)
            .outerjoin(Department, Department.id == Employee.department_id)
            .outerjoin(Position, Position.id == Employee.position_id)
            .where(Employee.deleted_at.is_(None))
            .order_by(Organization.name, Employee.full_name))
    if not args.all:
        stmt = stmt.where(Employee.status == "active")
    if args.inn:
        stmt = stmt.where(Organization.inn == args.inn)

    with tenant_session(bypass=True) as db:
        rows = db.execute(stmt).all()

    out = Path(get_settings().storage_dir) / f"employees_{date.today().isoformat()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    status = {"active": "Активен", "inactive": "Деактивирован"}
    # utf-8-sig и «;» — чтобы русский Excel открыл файл сразу правильно
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Организация", "ИНН", "ФИО", "Подразделение", "Должность", "Телефон",
                    "Дата приёма", "Статус"])
        for org, inn, name, dept, pos, phone, hired, st in rows:
            w.writerow([org, inn or "", name, dept or "", pos or "", phone or "",
                        hired.strftime("%d.%m.%Y") if hired else "", status.get(st, st)])
    print(f"Готово: выгружено {len(rows)} сотрудников. Файл: storage\\{out.name}")


if __name__ == "__main__":
    main()
