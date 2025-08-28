from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.reminders import Reminder


def create_reminder(session: Session, text: str, remind_at: datetime, user_id: Optional[int]) -> Reminder:
	rem = Reminder(text=text, remind_at=remind_at, user_id=user_id, is_sent=False)
	session.add(rem)
	session.commit()
	session.refresh(rem)
	return rem


def list_active_reminders(session: Session) -> List[Reminder]:
	return session.query(Reminder).filter_by(is_sent=False).order_by(Reminder.remind_at.asc()).all()


def cancel_reminder(session: Session, reminder_id: int) -> bool:
	rem = session.get(Reminder, reminder_id)
	if not rem or rem.is_sent:
		return False
	session.delete(rem)
	session.commit()
	return True


def mark_sent(session: Session, reminder_id: int) -> None:
	rem = session.get(Reminder, reminder_id)
	if not rem:
		return
	rem.is_sent = True
	session.commit()


def delete_sent_before(session: Session, before: datetime) -> int:
	"""Удаляет отправленные напоминания со временем <= before. Возвращает число удалённых."""
	q = session.query(Reminder).filter(Reminder.is_sent == True, Reminder.remind_at <= before)  # noqa: E712
	count = q.count()
	q.delete(synchronize_session=False)
	session.commit()
	return count