"""Свои материалы и курсы у заказчиков

org_id IS NULL — общие (ведёт учебный центр, видят все заказчики);
org_id = организация — личные материалы и курсы заказчика (видит только он и учебный центр).

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TABLES = ("library_folders", "library_items", "courses")
ZERO = "'00000000-0000-0000-0000-000000000000'::uuid"


def upgrade() -> None:
    for t in TABLES:
        op.add_column(t, sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id")))
        op.create_index(f"ix_{t}_org", t, ["org_id"])

    op.drop_index("uq_library_folder_name", "library_folders")
    op.create_index("uq_library_folder_name", "library_folders",
                    [sa.text(f"coalesce(org_id, {ZERO})"), sa.text(f"coalesce(parent_id, {ZERO})"),
                     sa.text("lower(name)")],
                    unique=True, postgresql_where=sa.text("deleted_at IS NULL"))

    # Читать: общее + своё. Изменять: только своё (учебный центр — всё через bypass).
    for t in ("library_folders", "library_items"):
        op.execute(f"DROP POLICY center_only ON {t}")
    op.execute("ALTER TABLE courses ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE courses FORCE ROW LEVEL SECURITY")
    for t in TABLES:
        op.execute(f"""CREATE POLICY read_shared ON {t} FOR SELECT
            USING (app_bypass() OR org_id IS NULL OR org_id = app_current_org())""")
        op.execute(f"""CREATE POLICY write_own ON {t}
            USING (app_bypass() OR org_id = app_current_org())
            WITH CHECK (app_bypass() OR org_id = app_current_org())""")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"DROP POLICY read_shared ON {t}")
        op.execute(f"DROP POLICY write_own ON {t}")
    op.execute("ALTER TABLE courses NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE courses DISABLE ROW LEVEL SECURITY")
    for t in ("library_folders", "library_items"):
        op.execute(f"CREATE POLICY center_only ON {t} USING (app_bypass()) WITH CHECK (app_bypass())")
    op.drop_index("uq_library_folder_name", "library_folders")
    op.create_index("uq_library_folder_name", "library_folders",
                    [sa.text(f"coalesce(parent_id, {ZERO})"), sa.text("lower(name)")],
                    unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    for t in TABLES:
        op.drop_index(f"ix_{t}_org", t)
        op.drop_column(t, "org_id")
