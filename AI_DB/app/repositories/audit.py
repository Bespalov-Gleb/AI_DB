from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_event(session: Session, action: str, resource: Optional[str] = None, actor: Optional[str] = None, payload: Optional[Dict[str, Any]] = None, result: Optional[str] = None) -> AuditLog:
	entry = AuditLog(action=action, resource=resource, actor=actor, payload=payload, result=result)
	session.add(entry)
	session.commit()
	session.refresh(entry)
	return entry


def list_audit(session: Session, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None) -> List[AuditLog]:
	q = session.query(AuditLog)
	if date_from is not None:
		q = q.filter(AuditLog.created_at >= date_from)
	if date_to is not None:
		q = q.filter(AuditLog.created_at <= date_to)
	return q.order_by(AuditLog.id.desc()).all()