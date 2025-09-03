from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column
from zoneinfo import ZoneInfo

from app.db import Base


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    remind_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Asia/Tashkent")))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Asia/Tashkent")), onupdate=lambda: datetime.now(ZoneInfo("Asia/Tashkent")))