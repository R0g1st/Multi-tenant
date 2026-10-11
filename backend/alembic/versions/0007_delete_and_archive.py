"""Удаление записей в панели БД и архив «Прервано или закрыто»

1. Внешние ключи получают правила ON DELETE, поэтому строку можно удалить в Adminer
   (раньше PostgreSQL отказывал: «на запись ещё ссылаются из таблицы …»):
   - удаление заказчика удаляет всё, что ему принадлежит (входы, сотрудников, курсы, обучение…);
   - удаление сотрудника или курса удаляет его назначения и попытки тестов;
   - ссылки «кто сделал» (журнал, «назначил», «загрузил») и необязательные ссылки
     (подразделение, должность, вход сотрудника, папка материала) просто очищаются.
2. employees.deactivated_at — когда сотрудника отключили (через 7 дней он уходит в архив).
3. employee_archive — архив сотрудников, удалённых из рабочих таблиц. Видит только главный администратор.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# (таблица, колонка, на кого ссылается, действие при удалении)
RULES = [
    ("users", "org_id", "organizations", "CASCADE"),
    ("employees", "org_id", "organizations", "CASCADE"),
    ("departments", "org_id", "organizations", "CASCADE"),
    ("positions", "org_id", "organizations", "CASCADE"),
    ("courses", "org_id", "organizations", "CASCADE"),
    ("assignments", "org_id", "organizations", "CASCADE"),
    ("test_attempts", "org_id", "organizations", "CASCADE"),
    ("library_folders", "org_id", "organizations", "CASCADE"),
    ("library_items", "org_id", "organizations", "CASCADE"),
    ("audit_logs", "org_id", "organizations", "SET NULL"),
    ("audit_logs", "actor_user_id", "users", "SET NULL"),
    ("employees", "user_id", "users", "SET NULL"),
    ("employees", "department_id", "departments", "SET NULL"),
    ("employees", "position_id", "positions", "SET NULL"),
    ("assignments", "assigned_by", "users", "SET NULL"),
    ("assignments", "course_id", "courses", "CASCADE"),
    ("assignments", "employee_id", "employees", "CASCADE"),
    ("test_attempts", "assignment_id", "assignments", "CASCADE"),
    ("course_materials", "item_id", "library_items", "CASCADE"),
    ("library_folders", "parent_id", "library_folders", "CASCADE"),
    ("library_items", "folder_id", "library_folders", "SET NULL"),
    ("library_items", "uploaded_by", "users", "SET NULL"),
]


def _set_rules(restore: bool) -> None:
    bind = op.get_bind()
    for table, column, target, action in RULES:
        name = bind.exec_driver_sql(
            """SELECT c.conname FROM pg_constraint c
               JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
               WHERE c.contype = 'f' AND c.conrelid = %s::regclass AND a.attname = %s""",
            (table, column)).scalar_one()
        rule = "" if restore else f" ON DELETE {action}"
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"')
        op.execute(f'ALTER TABLE {table} ADD CONSTRAINT "{name}" FOREIGN KEY ({column}) '
                   f"REFERENCES {target}(id){rule}")


def upgrade() -> None:
    _set_rules(restore=False)

    op.add_column("employees", sa.Column("deactivated_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE employees SET deactivated_at = updated_at WHERE status = 'inactive'")
    op.execute("COMMENT ON COLUMN employees.deactivated_at IS 'Отключён (через 7 дней — в архив)'")

    op.create_table(
        "employee_archive",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),  # прежний ID сотрудника
        sa.Column("org_id", pg.UUID(as_uuid=True)),  # без внешнего ключа: заказчика могут удалить позже
        sa.Column("org_name", sa.String(300)),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("position_name", sa.String(200)),
        sa.Column("department_name", sa.String(200)),
        sa.Column("phone", sa.String(16)),
        sa.Column("deactivated_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("data", pg.JSONB, nullable=False),  # всё о сотруднике на момент удаления, включая обучение
    )
    op.create_index("ix_employee_archive_archived", "employee_archive", ["archived_at"])
    # Только сессии учебного центра; на сайте раздел открыт лишь главному администратору.
    op.execute("ALTER TABLE employee_archive ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_archive FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY center_only ON employee_archive USING (app_bypass()) WITH CHECK (app_bypass())")
    op.execute("GRANT SELECT, INSERT, DELETE ON employee_archive TO ohs_app")
    comments = {
        "id": "ID сотрудника", "org_id": "ID заказчика", "org_name": "Заказчик", "full_name": "ФИО",
        "position_name": "Должность", "department_name": "Подразделение", "phone": "Телефон",
        "deactivated_at": "Отключён", "archived_at": "Перенесён в архив",
        "data": "Все данные (сотрудник, вход, обучение)",
    }
    op.execute("COMMENT ON TABLE employee_archive IS 'Прервано или закрыто (архив сотрудников)'")
    for column, label in comments.items():
        op.execute(f"COMMENT ON COLUMN employee_archive.{column} IS '{label}'")


def downgrade() -> None:
    op.drop_table("employee_archive")
    op.drop_column("employees", "deactivated_at")
    _set_rules(restore=True)
