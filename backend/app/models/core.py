"""Модели этапа 1: доступ, организации, структура, сотрудники, аудит.

Роли — фиксированный набор значений поля users.role (отдельная таблица
ролей не нужна: список ролей задан ТЗ и меняется только вместе с кодом).
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROLES = ("superadmin", "center_admin", "ohs_engineer", "org_admin", "employee")


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(300))
    inn: Mapped[str | None] = mapped_column(String(12))
    kpp: Mapped[str | None] = mapped_column(String(9))
    legal_address: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    responsible_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), server_default="active")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    phone: Mapped[str] = mapped_column(String(16), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = _created()


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    birth_date: Mapped[date | None] = mapped_column(Date)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    position_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("positions.id"))
    phone: Mapped[str | None] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(254))
    hired_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), server_default="active")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
