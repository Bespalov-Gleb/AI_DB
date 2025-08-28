from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ListingType(str, Enum):
    sale = "sale"
    demand = "demand"
    contract = "contract"


class ParsedListing(BaseModel):
    title: str = Field(..., description="Наименование товара")
    description: Optional[str] = Field(None, description="Описание товара")
    characteristics: Optional[Dict[str, Any]] = Field(None, description="Характеристики в виде словаря")
    quantity: Optional[int] = Field(None, description="Количество")
    price: Optional[Decimal] = Field(None, description="Цена")
    location: Optional[str] = Field(None, description="Местонахождение")
    contact: Optional[str] = Field(None, description="Контактные данные")
    photo_links: Optional[List[str]] = Field(None, description="Ссылки на фото")
    type: ListingType = Field(..., description="Тип записи: sale/demand/contract")

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "станок отрезной",
                "description": "станок, б/у, состояние хорошее",
                "characteristics": {"мощность": "2кВт"},
                "quantity": 1,
                "price": 120000.00,
                "location": "Челябинск",
                "contact": "Алексей, +7 912 000-00-00",
                "photo_links": ["https://.../photo1.jpg"],
                "type": "sale",
            }
        }
    }