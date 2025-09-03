from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, Text, Numeric, Enum, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from zoneinfo import ZoneInfo

from app.db import Base


class ListingTypeEnum(str):
    SALE = "sale"
    DEMAND = "demand"
    CONTRACT = "contract"


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    characteristics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    photo_links: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    type: Mapped[str] = mapped_column(Enum(ListingTypeEnum.SALE, ListingTypeEnum.DEMAND, ListingTypeEnum.CONTRACT, name="listing_type"), nullable=False)

	created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Asia/Tashkent")))
	updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Asia/Tashkent")), onupdate=lambda: datetime.now(ZoneInfo("Asia/Tashkent")))