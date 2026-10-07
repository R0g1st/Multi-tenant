"""Начальная схема: доступ, организации, сотрудники, аудит + RLS

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
NOW = sa.text("now()")
ROLES = "('superadmin','center_admin','ohs_engineer','org_admin','employee')"

# таблицы, строки которых принадлежат организации
TENANT_TABLES = ["users", "departments", "positions", "employees", "audit_logs"]


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app_current_org() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.current_org', true), '')::uuid $$;
    """)
    op.execute("""
        CREATE FUNCTION app_bypass() RETURNS boolean LANGUAGE sql STABLE AS
        $$ SELECT coalesce(current_setting('app.bypass_rls', true), '') = 'on' $$;
    """)

    op.create_table(
        "organizations",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("inn", sa.String(12)),
        sa.Column("kpp", sa.String(9)),
        sa.Column("legal_address", sa.Text),
        sa.Column("contact_phone", sa.String(20)),
        sa.Column("contact_email", sa.String(254)),
        sa.Column("responsible_name", sa.String(200)),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active','blocked')", name="ck_org_status"),
    )
    op.create_index("uq_org_inn_alive", "organizations", ["inn"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL AND inn IS NOT NULL"))

    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id")),
        sa.Column("phone", sa.String(16), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(f"role IN {ROLES}", name="ck_users_role"),
        # сотрудники центра — без организации; администратор организации и сотрудник — только с ней
        sa.CheckConstraint(
            "(role IN ('superadmin','center_admin') AND org_id IS NULL) OR "
            "(role IN ('org_admin','employee') AND org_id IS NOT NULL) OR "
            "role = 'ohs_engineer'",
            name="ck_users_role_org",
        ),
    )
    op.create_index("ix_users_org", "users", ["org_id"])

    op.create_table(
        "refresh_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(300)),
        sa.Column("ip", pg.INET),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_refresh_user", "refresh_sessions", ["user_id"])

    for name in ("departments", "positions"):
        op.create_table(
            name,
            sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
            sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
        )
        op.create_index(f"uq_{name}_org_name", name, ["org_id", "name"], unique=True,
                        postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "employees",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("birth_date", sa.Date),
        sa.Column("department_id", pg.UUID(as_uuid=True), sa.ForeignKey("departments.id")),
        sa.Column("position_id", pg.UUID(as_uuid=True), sa.ForeignKey("positions.id")),
        sa.Column("phone", sa.String(16)),
        sa.Column("email", sa.String(254)),
        sa.Column("hired_at", sa.Date),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active','inactive')", name="ck_employee_status"),
    )
    op.create_index("ix_employees_org_dept", "employees", ["org_id", "department_id"])
    op.create_index("ix_employees_org_name", "employees", ["org_id", "full_name"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("actor_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("description", sa.Text),
        sa.Column("details", pg.JSONB),
        sa.Column("ip", pg.INET),
    )
    op.create_index("ix_audit_org_at", "audit_logs", ["org_id", "at"])

    # ---- Права рабочей роли приложения ----
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ohs_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ohs_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ohs_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ohs_app")
    # журнал аудита только дописывается
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM ohs_app")

    # ---- Row-Level Security ----
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY tenant_isolation ON organizations
        USING (app_bypass() OR id = app_current_org())
        WITH CHECK (app_bypass() OR id = app_current_org())""")
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant_isolation ON {t}
            USING (app_bypass() OR org_id = app_current_org())
            WITH CHECK (app_bypass() OR org_id = app_current_org())""")


def downgrade() -> None:
    for t in ["audit_logs", "employees", "positions", "departments", "refresh_sessions", "users", "organizations"]:
        op.drop_table(t)
    op.execute("DROP FUNCTION app_bypass()")
    op.execute("DROP FUNCTION app_current_org()")
