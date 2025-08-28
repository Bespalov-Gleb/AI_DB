from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models.listings import Listing
from app.models.photos import Photo


@dataclass
class DiagnosticIssue:
	severity: str  # info|warn|error
	message: str
	listing_id: int | None = None


_PHONE_RE = re.compile(r"^\+?\d{10,15}$")


def _is_valid_phone(value: str | None) -> bool:
	if not value:
		return False
	# Извлекаем номер из 'Имя, +7...' если нужно
	if "," in value:
		value = value.split(",", 1)[1].strip()
	val = re.sub(r"[\s\-()]+", "", value)
	return bool(_PHONE_RE.match(val))


def run_diagnostics(session: Session) -> Tuple[str, List[DiagnosticIssue]]:
	issues: List[DiagnosticIssue] = []
	listings: List[Listing] = session.query(Listing).all()
	photos = session.query(Photo).all()
	photos_by_listing: dict[int, List[Photo]] = {}
	for p in photos:
		photos_by_listing.setdefault(p.listing_id, []).append(p)

	# Пустые или некорректные поля
	for l in listings:
		if not l.title or not l.type:
			issues.append(DiagnosticIssue("error", "Пустые обязательные поля (title/type)", l.id))
		if l.price is not None and l.price < 0:
			issues.append(DiagnosticIssue("warn", "Отрицательная цена", l.id))
		if not l.contact or not _is_valid_phone(l.contact):
			issues.append(DiagnosticIssue("warn", "Контакт отсутствует или телефон некорректен", l.id))

	# Дубликаты по (title, location, type, price)
	seen: dict[tuple, int] = {}
	for l in listings:
		key = (l.title.strip().lower() if l.title else "", (l.location or '').strip().lower(), (l.type or '').strip().lower(), str(l.price) if l.price is not None else "")
		if key in seen:
			issues.append(DiagnosticIssue("warn", f"Возможный дубликат с записью #{seen[key]}", l.id))
		else:
			seen[key] = l.id

	# Фото: битые/пустые ссылки (только проверяем пустоту/формат)
	for l in listings:
		links = l.photo_links or []
		if links:
			for link in links:
				if not isinstance(link, str) or not link:
					issues.append(DiagnosticIssue("warn", "Пустая ссылка на фото", l.id))
		else:
			# если в таблице photos есть записи — ок; если нет, но ожидались? ТЗ не требует
			pass

	# Сформировать текстовый отчёт
	lines: List[str] = []
	lines.append("=== Диагностика ===")
	lines.append(f"Всего записей: {len(listings)}")
	lines.append(f"Найдено проблем: {len(issues)}")
	for i in issues:
		prefix = {"info": "[i]", "warn": "[!]", "error": "[x]"}.get(i.severity, "[?]")
		if i.listing_id:
			lines.append(f"{prefix} #{i.listing_id}: {i.message}")
		else:
			lines.append(f"{prefix} {i.message}")

	return "\n".join(lines), issues