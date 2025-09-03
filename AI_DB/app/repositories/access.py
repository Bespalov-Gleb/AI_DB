from __future__ import annotations
from datetime import datetime
from secrets import token_urlsafe
from typing import Optional, List
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.access_tokens import AccessToken


def create_token(session: Session, expires_at: Optional[datetime]) -> AccessToken:
	value = token_urlsafe(32)
	entry = AccessToken(token=value, expires_at=expires_at)
	session.add(entry)
	session.commit()
	session.refresh(entry)
	return entry


def get_token(session: Session, value: str) -> Optional[AccessToken]:
	return session.query(AccessToken).filter_by(token=value).first()


def revoke_token(session: Session, value: str) -> bool:
	entry = get_token(session, value)
	if not entry:
		return False
	session.delete(entry)
	session.commit()
	return True


def list_tokens(session: Session) -> List[AccessToken]:
	return session.query(AccessToken).order_by(AccessToken.id.desc()).all()


def cleanup_expired(session: Session) -> int:
	now = datetime.now(ZoneInfo("Asia/Tashkent"))
	q = session.query(AccessToken).filter(AccessToken.expires_at.isnot(None), AccessToken.expires_at < now)
	count = q.count()
	for t in q.all():
		session.delete(t)
	session.commit()
	return count