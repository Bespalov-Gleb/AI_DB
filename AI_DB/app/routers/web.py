from __future__ import annotations
from math import ceil
from typing import Optional
import os
import json
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from starlette.background import BackgroundTask
from starlette.status import HTTP_303_SEE_OTHER
from fastapi.templating import Jinja2Templates

from app.db import session_scope
from app.models.listings import Listing
from app.services.storage import get_upload_dir
from app.repositories.listings import delete_listing_by_id
from app.repositories.audit import list_audit, log_event
from app.repositories.access import list_tokens as access_list, create_token as access_create, revoke_token as access_revoke
from app.config import get_settings
from app.security import require_web_access
from app.services.export import export_matches_to_excel


templates = Jinja2Templates(directory="app/templates")

# Локализация полей/значений для шаблонов
def _loc_type(val: str | None) -> str:
    if not val:
        return "-"
    m = {"sale": "продажа", "demand": "покупка", "contract": "контракт"}
    return m.get(str(val).lower(), str(val))

def _loc_action(val: str | None) -> str:
    if not val:
        return "-"
    m = {
        "create": "создание",
        "update": "изменение",
        "delete": "удаление",
        "attach_photo": "прикрепление фото",
        "reminder_sent": "напоминание отправлено",
        "gcal_reminder_sent": "напоминание (календарь)",
    }
    return m.get(str(val).lower(), str(val))

def _loc_resource(val: str | None) -> str:
    if not val:
        return "-"
    m = {"listing": "запись", "reminder": "напоминание", "gcal": "календарь"}
    return m.get(str(val).lower(), str(val))

templates.env.filters["loc_type"] = _loc_type
templates.env.filters["loc_action"] = _loc_action
templates.env.filters["loc_resource"] = _loc_resource

def _format_datetime(dt) -> str:
    if dt is None:
        return "-"
    try:
        # Если время уже в московской таймзоне, просто форматируем
        if dt.tzinfo == ZoneInfo("Europe/Moscow"):
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        # Если время naive (без таймзоны), считаем что это UTC и конвертируем в московское
        elif dt.tzinfo is None:
            from datetime import timezone
            utc_dt = dt.replace(tzinfo=timezone.utc)
            moscow_dt = utc_dt.astimezone(ZoneInfo("Europe/Moscow"))
            return moscow_dt.strftime("%Y-%m-%d %H:%M:%S")
        # Если время в другой таймзоне, конвертируем в московское
        else:
            moscow_dt = dt.astimezone(ZoneInfo("Europe/Moscow"))
            return moscow_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt)

templates.env.filters["format_datetime"] = _format_datetime
 
# Красивое русскоязычное представление деталей журнала
def _translate_field_name(name: str) -> str:
    mapping = {
        "title": "наименование",
        "type": "тип",
        "location": "город",
        "price": "цена",
        "quantity": "количество",
        "contact": "контакт",
        "description": "описание",
        "characteristics": "характеристики",
        "url": "ссылка",
        "changed": "изменены поля",
    }
    return mapping.get(name, name)

def _loc_payload(payload) -> str:
    try:
        if payload is None:
            return "-"
        # Если это уже строка — вернуть как есть
        if isinstance(payload, str):
            return payload
        # Список — перечислить через запятую
        if isinstance(payload, list):
            return ", ".join(str(x) for x in payload)
        # Словарь — собрать читаемую строку
        if isinstance(payload, dict):
            parts: list[str] = []
            listing_id = payload.get("listing_id")
            if listing_id is not None:
                parts.append(f"запись #{listing_id}")
            # Остальные поля, в человеко-читаемом виде
            for key, value in payload.items():
                if key == "listing_id":
                    continue
                if key == "type":
                    parts.append(f"{_translate_field_name(key)}: {_loc_type(str(value))}")
                elif key == "changed":
                    if isinstance(value, list) and len(value) == 0:
                        parts.append("изменения: нет")
                    else:
                        names = []
                        if isinstance(value, list):
                            for f in value:
                                names.append(_translate_field_name(str(f)))
                        else:
                            names.append(_translate_field_name(str(value)))
                        parts.append(f"изменены поля: {', '.join(names)}")
                else:
                    parts.append(f"{_translate_field_name(key)}: {value}")
            return "; \n".join(parts)
        # На всё прочее — просто строковое представление
        return str(payload)
    except Exception:
        return str(payload)

templates.env.filters["loc_payload"] = _loc_payload
router = APIRouter()


# Нормализация значения типа из строки запроса (русское → enum)
def _normalize_ltype(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().lower()
    mapping = {
        # английские значения — как есть
        "sale": "sale",
        "demand": "demand",
        "contract": "contract",
        # русские варианты
        "продажа": "sale",
		"спрос": "demand",
        "покупка": "demand",
        "контракт": "contract",
        "договор": "contract",
    }
    return mapping.get(v)

@router.get("/", response_class=HTMLResponse)
async def list_view(request: Request, city: Optional[str] = None, ltype: Optional[str] = Query(None, alias="type"), q: Optional[str] = None, fuzzy_token_threshold: float = 0.6, page: int = 1, per_page: int = 10, _=Depends(require_web_access)):
	page = max(1, page)
	per_page = min(50, max(1, per_page))
	from app.services.matching import title_similarity
	with session_scope() as session:
		query = session.query(Listing)
		if city:
			query = query.filter(Listing.location == city)
		# приведём русские варианты типа к enum
		norm_ltype = _normalize_ltype(ltype)
		if norm_ltype:
			query = query.filter(Listing.type == norm_ltype)
		total = query.count()
		items = query.order_by(Listing.id.desc()).all()
		# Подборки: последние 10 записей без фильтров (для карусели)
		featured = session.query(Listing).order_by(Listing.id.desc()).limit(10).all()
	# Фильтр по наименованию с Левенштейном на приложении
	if q:
		needle = q.strip()
		scored = []
		for it in items:
			score = title_similarity(needle, it.title, fuzzy_token_threshold=fuzzy_token_threshold)
			if score >= 0.6:  # отсечка по умолчанию
				scored.append((score, it))
		scored.sort(key=lambda t: t[0], reverse=True)
		items = [it for _, it in scored]
		total = len(items)
	# Пагинация после фильтра
	page = max(1, page)
	per_page = min(50, max(1, per_page))
	pages = ceil(total / per_page) if per_page else 1
	start = (page - 1) * per_page
	end = start + per_page
	items = items[start:end]
	# в поле ввода вернём исходное значение пользователя
	return templates.TemplateResponse("list.html", {"request": request, "items": items, "featured": featured, "total": total, "page": page, "pages": pages, "per_page": per_page, "city": city, "ltype": ltype, "q": q, "fuzzy_token_threshold": fuzzy_token_threshold})


@router.get("/detail/{listing_id}", response_class=HTMLResponse)
async def detail_view(request: Request, listing_id: int, _=Depends(require_web_access)):
	with session_scope() as session:
		item = session.get(Listing, listing_id)
		if not item:
			return templates.TemplateResponse("not_found.html", {"request": request, "id": listing_id}, status_code=404)
		# Разрешим ссылки на фото: file:// → /uploads/<имя>, если файл существует в каталоге загрузок
		photos = []
		upload_dir = get_upload_dir()
		for link in (item.photo_links or []):
			try:
				if isinstance(link, str) and link.startswith("file://"):
					fname = link.split("/")[-1]
					candidate = upload_dir / fname
					if candidate.exists():
						photos.append(f"/uploads/{fname}")
					else:
						photos.append(link)
				else:
					photos.append(link)
			except Exception:
				photos.append(link)
	return templates.TemplateResponse("detail.html", {"request": request, "item": item, "photos": photos})


@router.get("/detail/{listing_id}/edit", response_class=HTMLResponse)
async def edit_view(request: Request, listing_id: int, _=Depends(require_web_access)):
	with session_scope() as session:
		item = session.get(Listing, listing_id)
		if not item:
			return templates.TemplateResponse("not_found.html", {"request": request, "id": listing_id}, status_code=404)
	return templates.TemplateResponse("edit.html", {"request": request, "item": item})


@router.post("/detail/{listing_id}/edit")
async def edit_submit(request: Request, listing_id: int, _=Depends(require_web_access)):
	form = await request.form()
	def _none_if_empty(v: str | None):
		if v is None:
			return None
		vv = v.strip()
		return vv if vv != "" else None
	def _to_decimal(v: str | None):
		v = _none_if_empty(v)
		if v is None:
			return None
		try:
			return Decimal(str(v).replace(" ", ""))
		except Exception:
			return None
	def _to_int(v: str | None):
		v = _none_if_empty(v)
		if v is None:
			return None
		try:
			return int(v)
		except Exception:
			return None
	with session_scope() as session:
		item = session.get(Listing, listing_id)
		if not item:
			return RedirectResponse(url="/web", status_code=HTTP_303_SEE_OTHER)
		item.type = _none_if_empty(form.get("type")) or item.type
		item.title = _none_if_empty(form.get("title")) or item.title
		item.description = _none_if_empty(form.get("description"))
		item.quantity = _to_int(form.get("quantity"))
		item.price = _to_decimal(form.get("price"))
		item.location = _none_if_empty(form.get("location"))
		item.contact = _none_if_empty(form.get("contact"))
		chars_raw = _none_if_empty(form.get("characteristics"))
		if chars_raw:
			try:
				item.characteristics = json.loads(chars_raw)
			except Exception:
				pass
	return RedirectResponse(url=f"/web/detail/{listing_id}", status_code=HTTP_303_SEE_OTHER)


@router.post("/detail/{listing_id}/delete")
async def delete_submit(request: Request, listing_id: int, _=Depends(require_web_access)):
	with session_scope() as session:
		ok = delete_listing_by_id(session, listing_id)
		if ok:
			client = request.client.host if request.client else None
			log_event(session, action="delete", resource="listing", actor=client or "web", payload={"listing_id": listing_id})
	return RedirectResponse(url="/web", status_code=HTTP_303_SEE_OTHER)


@router.get("/audit", response_class=HTMLResponse)
async def audit_view(request: Request, date_from: Optional[str] = None, date_to: Optional[str] = None, _=Depends(require_web_access)):
	from datetime import datetime
	_df = None
	_dt = None
	try:
		_df = datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
	except Exception:
		_df = None
	try:
		_dt = datetime.strptime(date_to, "%Y-%m-%d") if date_to else None
	except Exception:
		_dt = None
	with session_scope() as session:
		rows = list_audit(session, date_from=_df, date_to=_dt)
	return templates.TemplateResponse("audit.html", {"request": request, "rows": rows, "date_from": date_from, "date_to": date_to})


@router.get("/matches", response_class=HTMLResponse)
async def matches_view(request: Request, threshold: float = 0.45, w_title: float = 0.6, w_char: float = 0.2, w_loc: float = 0.15, w_price: float = 0.05, price_tolerance_abs: str | None = None, price_tolerance_pct: str | None = None, fuzzy_token_threshold: float = 0.6, _=Depends(require_web_access)):
	from app.services.matching import group_listings, find_matches
	from decimal import Decimal as _Dec
	# Безопасное приведение пустых значений к None
	pta_dec = None
	ptp_float = None
	try:
		if price_tolerance_abs is not None and str(price_tolerance_abs).strip() != "":
			pta_dec = _Dec(str(price_tolerance_abs).replace(",", ".").replace(" ", ""))
	except Exception:
		pta_dec = None
	try:
		if price_tolerance_pct is not None and str(price_tolerance_pct).strip() != "":
			ptp_float = float(str(price_tolerance_pct).replace(",", ".").replace(" ", ""))
	except Exception:
		ptp_float = None
	with session_scope() as session:
		items = session.query(Listing).all()
	demands, sales = group_listings(items)
	pairs = find_matches(
		demands,
		sales,
		threshold=threshold,
		w_title=w_title,
		w_char=w_char,
		w_loc=w_loc,
		w_price=w_price,
		price_tolerance_abs=pta_dec,
		price_tolerance_pct=ptp_float,
		fuzzy_token_threshold=fuzzy_token_threshold,
	)
	return templates.TemplateResponse("matches.html", {"request": request, "pairs": pairs, "threshold": threshold, "w_title": w_title, "w_char": w_char, "w_loc": w_loc, "w_price": w_price, "price_tolerance_abs": pta_dec, "price_tolerance_pct": ptp_float, "fuzzy_token_threshold": fuzzy_token_threshold})

@router.get("/matches/export")
async def matches_export(request: Request, threshold: float = 0.45, w_title: float = 0.6, w_char: float = 0.2, w_loc: float = 0.15, w_price: float = 0.05, price_tolerance_abs: str | None = None, price_tolerance_pct: str | None = None, fuzzy_token_threshold: float = 0.6, _=Depends(require_web_access)):
	from app.services.matching import group_listings, find_matches
	from datetime import datetime as _dt
	from decimal import Decimal as _Dec
	# Безопасное приведение пустых значений к None
	pta_dec = None
	ptp_float = None
	try:
		if price_tolerance_abs is not None and str(price_tolerance_abs).strip() != "":
			pta_dec = _Dec(str(price_tolerance_abs).replace(",", ".").replace(" ", ""))
	except Exception:
		pta_dec = None
	try:
		if price_tolerance_pct is not None and str(price_tolerance_pct).strip() != "":
			ptp_float = float(str(price_tolerance_pct).replace(",", ".").replace(" ", ""))
	except Exception:
		ptp_float = None
	with session_scope() as session:
		items = session.query(Listing).all()
	demands, sales = group_listings(items)
	pairs = find_matches(
		demands,
		sales,
		threshold=threshold,
		w_title=w_title,
		w_char=w_char,
		w_loc=w_loc,
		w_price=w_price,
		price_tolerance_abs=pta_dec,
		price_tolerance_pct=ptp_float,
		fuzzy_token_threshold=fuzzy_token_threshold,
	)
	rows = []
	for p in pairs:
		rows.append({
			"demand_id": p.Demand.id,
			"demand_title": p.Demand.title,
			"demand_location": p.Demand.location,
			"demand_price": float(p.Demand.price) if p.Demand.price is not None else None,
			"demand_contact": p.Demand.contact,
			"sale_id": p.Sale.id,
			"sale_title": p.Sale.title,
			"sale_location": p.Sale.location,
			"sale_price": float(p.Sale.price) if p.Sale.price is not None else None,
			"sale_contact": p.Sale.contact,
			"score": round(p.score, 3),
		})
	stamp = _dt.now(ZoneInfo("Europe/Moscow")).strftime("%Y%m%d_%H%M%S")
	filepath = os.path.abspath(f"matches_{stamp}.xlsx")
	export_matches_to_excel(rows, filepath)
	def _cleanup(path: str) -> None:
		try:
			os.remove(path)
		except Exception:
			pass
	return FileResponse(filepath, filename=os.path.basename(filepath), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", background=BackgroundTask(_cleanup, filepath))


@router.get("/tokens", response_class=HTMLResponse)
async def tokens_view(request: Request, _=Depends(require_web_access)):
	with session_scope() as session:
		items = access_list(session)
	settings = get_settings()
	base = settings.web_base_url.strip() if settings.web_base_url else f"http://localhost:{settings.app_port}"
	return templates.TemplateResponse("tokens.html", {"request": request, "items": items, "base": base})

@router.post("/tokens")
async def tokens_create(request: Request, _=Depends(require_web_access)):
	form = await request.form()
	minutes = form.get("minutes")
	from datetime import datetime, timedelta
	expires_at = None
	try:
		m = int(minutes) if minutes is not None else None
		if m and m > 0:
			expires_at = datetime.now(ZoneInfo("Europe/Moscow")) + timedelta(minutes=m)
	except Exception:
		pass
	with session_scope() as session:
		access_create(session, expires_at)
	return RedirectResponse(url="/web/tokens", status_code=HTTP_303_SEE_OTHER)

@router.post("/tokens/revoke")
async def tokens_revoke(request: Request, _=Depends(require_web_access)):
	form = await request.form()
	value = (form.get("token") or "").strip()
	with session_scope() as session:
		access_revoke(session, value)
	return RedirectResponse(url="/web/tokens", status_code=HTTP_303_SEE_OTHER)