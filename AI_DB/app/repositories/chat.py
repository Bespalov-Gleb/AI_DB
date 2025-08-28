from __future__ import annotations
from typing import List

from sqlalchemy.orm import Session

from app.models.chat_messages import ChatMessage


def add_message(session: Session, telegram_id: int, role: str, text: str) -> ChatMessage:
	msg = ChatMessage(telegram_id=str(telegram_id), role=role, text=text)
	session.add(msg)
	session.commit()
	session.refresh(msg)
	return msg


def get_last_messages(session: Session, telegram_id: int, limit: int = 10) -> List[ChatMessage]:
	limit = max(1, min(limit, 50))
	return (
		session.query(ChatMessage)
		.filter(ChatMessage.telegram_id == str(telegram_id))
		.order_by(ChatMessage.id.desc())
		.limit(limit)
		.all()
	)[::-1]

