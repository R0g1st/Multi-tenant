import ipaddress
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.deps import Actor
from app.models import AuditLog


def client_ip(request: Request) -> str | None:
    # За прокси (хостинг) здесь нужно будет учитывать X-Forwarded-For доверенного прокси.
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def log(db: Session, *, actor: Actor | None, action: str, entity_type: str,
        entity_id: object = None, description: str, org_id: UUID | None = None,
        details: dict | None = None, ip: str | None = None, actor_id: UUID | None = None) -> None:
    """Запись в журнал. Пароли и токены в details передавать нельзя."""
    db.add(AuditLog(
        actor_user_id=actor.id if actor else actor_id,
        org_id=org_id, action=action, entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        description=description, details=details, ip=ip))
