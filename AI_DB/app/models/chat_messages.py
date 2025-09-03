from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from zoneinfo import ZoneInfo

from app.db import Base


class ChatMessage(Base):
	__tablename__ = "chat_messages"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	telegram_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
	role: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" | "assistant"
	text: Mapped[str] = mapped_column(Text, nullable=False)

	created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Asia/Tashkent")))
