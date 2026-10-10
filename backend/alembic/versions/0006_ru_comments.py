"""Русские названия таблиц и колонок (комментарии в БД)

Показываются в Adminer (http://localhost:8080) вместо технических имён.
Структура таблиц не меняется.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

COMMON = {
    "id": "ID",
    "org_id": "Заказчик",
    "created_at": "Создано",
    "updated_at": "Изменено",
    "deleted_at": "Удалено",
}

TABLES = {
    "organizations": ("Заказчики", {
        "name": "Название", "inn": "ИНН", "kpp": "КПП", "legal_address": "Юридический адрес",
        "contact_phone": "Телефон", "contact_email": "Эл. почта", "responsible_name": "Ответственный",
        "status": "Статус",
    }),
    "employees": ("Подчинённые (сотрудники заказчиков)", {
        "user_id": "Вход в систему", "full_name": "ФИО", "birth_date": "Дата рождения",
        "department_id": "Подразделение", "position_id": "Должность", "phone": "Телефон",
        "email": "Эл. почта", "hired_at": "Дата приёма", "status": "Статус",
    }),
    "users": ("Входы в систему (пользователи)", {
        "phone": "Телефон (логин)", "password_hash": "Пароль (хеш)", "full_name": "ФИО", "role": "Роль",
        "is_active": "Активен", "must_change_password": "Сменить пароль при входе",
        "last_login_at": "Последний вход", "failed_login_count": "Неудачных попыток",
        "locked_until": "Заблокирован до",
    }),
    "departments": ("Подразделения", {"name": "Название"}),
    "positions": ("Должности", {"name": "Название"}),
    "courses": ("Курсы", {
        "title": "Название", "description": "Описание", "pass_score": "Проходной балл, %",
        "validity_months": "Действует, мес.", "test": "Тест",
    }),
    "course_materials": ("Материалы курсов", {
        "course_id": "Курс", "item_id": "Материал", "position": "Порядок",
    }),
    "assignments": ("Назначенное обучение", {
        "course_id": "Курс", "employee_id": "Сотрудник", "assigned_by": "Назначил",
        "assigned_at": "Назначено", "due_date": "Срок", "status": "Статус",
        "viewed": "Просмотренные материалы", "attempts": "Попыток", "score": "Лучший результат, %",
        "completed_at": "Пройдено", "expires_at": "Действует до", "cancelled_at": "Отменено",
    }),
    "test_attempts": ("Попытки тестов", {
        "assignment_id": "Назначение", "finished_at": "Завершено", "score": "Результат, %",
        "passed": "Сдан", "answers": "Ответы",
    }),
    "library_folders": ("Папки библиотеки", {"parent_id": "Родительская папка", "name": "Название"}),
    "library_items": ("Материалы библиотеки", {
        "folder_id": "Папка", "title": "Название", "description": "Описание", "kind": "Тип",
        "file_name": "Имя файла", "stored_name": "Файл на диске", "mime": "Формат", "size": "Размер, байт",
        "uploaded_by": "Загрузил",
    }),
    "audit_logs": ("Журнал действий", {
        "at": "Время", "actor_user_id": "Кто", "action": "Действие", "entity_type": "Объект",
        "entity_id": "ID объекта", "description": "Описание", "details": "Подробности", "ip": "IP-адрес",
    }),
    "refresh_sessions": ("Сеансы входа", {
        "user_id": "Пользователь", "token_hash": "Токен (хеш)", "expires_at": "Истекает",
        "revoked_at": "Отозван", "user_agent": "Браузер", "ip": "IP-адрес",
    }),
}


def _q(text: str | None) -> str:
    return "NULL" if text is None else "'" + text.replace("'", "''") + "'"


def _existing_columns(table: str) -> set[str]:
    rows = op.get_bind().exec_driver_sql(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s",
        (table,)).all()
    return {r[0] for r in rows}


def _apply(clear: bool) -> None:
    op.execute(f"COMMENT ON TABLE alembic_version IS {_q(None if clear else 'Служебная: версия схемы')}")
    for table, (title, columns) in TABLES.items():
        op.execute(f"COMMENT ON TABLE {table} IS {_q(None if clear else title)}")
        existing = _existing_columns(table)
        for column, label in {**COMMON, **columns}.items():
            if column in existing:
                op.execute(f'COMMENT ON COLUMN {table}."{column}" IS {_q(None if clear else label)}')


def upgrade() -> None:
    _apply(clear=False)


def downgrade() -> None:
    _apply(clear=True)
