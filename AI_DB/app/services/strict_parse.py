from __future__ import annotations
import re
from decimal import Decimal
from typing import Tuple

from app.schemas.listing_parse import ParsedListing, ListingType


_WORD_TO_INT = {
	"ноль": 0,
	"один": 1, "одна": 1, "1": 1,
	"два": 2, "две": 2, "2": 2,
	"три": 3, "3": 3,
	"четыре": 4, "4": 4,
	"пять": 5, "5": 5,
}

_TYPE_MAP = {
	"продажа": ListingType.sale,
	"продаю": ListingType.sale,
	"продам": ListingType.sale,
	"sale": ListingType.sale,
	"покупка": ListingType.demand,
	"спрос": ListingType.demand,
	"куплю": ListingType.demand,
	"demand": ListingType.demand,
	"договор": ListingType.contract,
	"contract": ListingType.contract,
}


class ParseError(ValueError):
	pass


def _require(condition: bool, message: str) -> None:
	if not condition:
		raise ParseError(message)


def _parse_quantity(text: str) -> int:
	val = text.strip().lower().replace("шт", "").replace("штук", "").replace("штуки", "").strip()
	if val in _WORD_TO_INT:
		return int(_WORD_TO_INT[val])
	m = re.search(r"\d+", val)
	_require(m is not None, "Количество: укажите число (например, 1 или 'одна')")
	return int(m.group(0))


def _parse_phone(text: str) -> str:
	candidate = re.sub(r"[\s\-()]+", "", text)
	m = re.match(r"^\+?\d{10,15}$", candidate)
	_require(m is not None, "Телефон: используйте формат +7XXXXXXXXXX")
	if not candidate.startswith("+"):
		candidate = "+" + candidate
	return candidate


def _parse_price(text: str) -> Decimal:
	digits = re.sub(r"[^0-9]", "", text)
	_require(digits != "", "Цена: укажите число (напр., 120000 или 120 000 руб)")
	return Decimal(digits)


def _parse_type(text: str) -> ListingType:
	key = text.strip().lower()
	_require(key in _TYPE_MAP, "Тип: используйте одно из значений: продажа | покупка (спрос) | договор")
	return _TYPE_MAP[key]


def parse_strict_listing(payload: str) -> ParsedListing:
	# Формат: title, quantity, city, name, phone, price, type
	parts = [p.strip() for p in payload.split(",")]
	_require(len(parts) >= 7, "Ожидается 7 полей: Наименование, Количество, Город, Имя, Телефон, Цена, Тип")
	# Если больше 7, склеим избыточные в описание
	(title_raw, qty_raw, city_raw, name_raw, phone_raw, price_raw, type_raw) = parts[:7]
	_require(title_raw != "", "Наименование: не может быть пустым")
	quantity = _parse_quantity(qty_raw)
	_require(quantity > 0, "Количество должно быть больше 0")
	city = city_raw.strip()
	_require(city != "", "Город: не может быть пустым")
	name = name_raw.strip()
	_require(name != "", "Имя: не может быть пустым")
	phone = _parse_phone(phone_raw)
	price = _parse_price(price_raw)
	ltype = _parse_type(type_raw)
	# Остаток как описание
	description = None
	if len(parts) > 7:
		description = ", ".join(parts[7:]).strip() or None
	contact = f"{name}, {phone}"
	return ParsedListing(
		title=title_raw,
		description=description,
		characteristics=None,
		quantity=quantity,
		price=price,
		location=city,
		contact=contact,
		photo_links=None,
		type=ltype,
	)