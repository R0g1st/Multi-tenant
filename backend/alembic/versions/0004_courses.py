"""Курсы из материалов библиотеки, тесты, назначение обучения и попытки

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
NOW = sa.text("now()")


def upgrade() -> None:
    # Каталог курсов общий (ведёт учебный центр); доступ к нему ограничивает API.
    op.create_table(
        "courses",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("pass_score", sa.Integer, nullable=False, server_default="80"),
        sa.Column("validity_months", sa.Integer),
        # [{"text": ..., "multiple": bool, "options": [{"text": ..., "correct": bool}]}]
        sa.Column("test", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("pass_score BETWEEN 1 AND 100", name="ck_course_pass_score"),
        sa.CheckConstraint("validity_months IS NULL OR validity_months > 0", name="ck_course_validity"),
    )
    op.create_table(
        "course_materials",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("course_id", pg.UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", pg.UUID(as_uuid=True), sa.ForeignKey("library_items.id"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("course_id", "item_id", name="uq_course_material"),
    )
    op.create_index("ix_course_materials_item", "course_materials", ["item_id"])

    # Назначения и попытки принадлежат организации — изолируются RLS, как сотрудники.
    op.create_table(
        "assignments",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("course_id", pg.UUID(as_uuid=True), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("employee_id", pg.UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("assigned_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("due_date", sa.Date),
        sa.Column("status", sa.String(20), nullable=False, server_default="assigned"),
        sa.Column("viewed", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("score", sa.Integer),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.Date),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('assigned','in_progress','passed')", name="ck_assignment_status"),
    )
    op.create_index("ix_assignments_org_status", "assignments", ["org_id", "status"])
    op.create_index("ix_assignments_employee", "assignments", ["employee_id"])
    # один и тот же курс нельзя назначить сотруднику дважды, пока прошлое назначение не завершено
    op.create_index("uq_assignment_open", "assignments", ["employee_id", "course_id"], unique=True,
                    postgresql_where=sa.text("cancelled_at IS NULL AND status <> 'passed'"))

    op.create_table(
        "test_attempts",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("assignment_id", pg.UUID(as_uuid=True), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("answers", pg.JSONB, nullable=False),
    )
    op.create_index("ix_test_attempts_assignment", "test_attempts", ["assignment_id"])

    for t in ("assignments", "test_attempts"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant_isolation ON {t}
            USING (app_bypass() OR org_id = app_current_org())
            WITH CHECK (app_bypass() OR org_id = app_current_org())""")


def downgrade() -> None:
    for t in ("test_attempts", "assignments", "course_materials", "courses"):
        op.drop_table(t)
