"""Четыре роли (без инженера по ОТ) и библиотека учебных материалов

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
NOW = sa.text("now()")


def upgrade() -> None:
    # ---- Роли: 1 superadmin, 2 center_admin (директор), 3 org_admin (заказчик), 4 employee ----
    op.execute("""UPDATE users SET role = CASE WHEN org_id IS NULL THEN 'center_admin' ELSE 'org_admin' END
                  WHERE role = 'ohs_engineer'""")
    op.drop_constraint("ck_users_role_org", "users")
    op.drop_constraint("ck_users_role", "users")
    op.create_check_constraint("ck_users_role", "users",
                               "role IN ('superadmin','center_admin','org_admin','employee')")
    op.create_check_constraint(
        "ck_users_role_org", "users",
        "(role IN ('superadmin','center_admin') AND org_id IS NULL) OR "
        "(role IN ('org_admin','employee') AND org_id IS NOT NULL)")

    # ---- Библиотека: общая для всех, управляют только сотрудники центра ----
    op.create_table(
        "library_folders",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("parent_id", pg.UUID(as_uuid=True), sa.ForeignKey("library_folders.id")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("uq_library_folder_name", "library_folders",
                    [sa.text("coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
                     sa.text("lower(name)")],
                    unique=True, postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "library_items",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("folder_id", pg.UUID(as_uuid=True), sa.ForeignKey("library_folders.id")),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("file_name", sa.String(300), nullable=False),
        sa.Column("stored_name", sa.String(100), nullable=False, unique=True),
        sa.Column("mime", sa.String(150), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("uploaded_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('document','video')", name="ck_library_item_kind"),
    )
    op.create_index("ix_library_items_folder", "library_items", ["folder_id"])

    # Строки библиотеки видны только сессиям учебного центра (у них включён bypass);
    # пользователи организаций не увидят их, даже если ошибка в коде откроет эндпоинт.
    for t in ("library_folders", "library_items"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY center_only ON {t} USING (app_bypass()) WITH CHECK (app_bypass())")


def downgrade() -> None:
    op.drop_table("library_items")
    op.drop_table("library_folders")
    op.drop_constraint("ck_users_role_org", "users")
    op.drop_constraint("ck_users_role", "users")
    op.create_check_constraint(
        "ck_users_role", "users",
        "role IN ('superadmin','center_admin','ohs_engineer','org_admin','employee')")
    op.create_check_constraint(
        "ck_users_role_org", "users",
        "(role IN ('superadmin','center_admin') AND org_id IS NULL) OR "
        "(role IN ('org_admin','employee') AND org_id IS NOT NULL) OR role = 'ohs_engineer'")
