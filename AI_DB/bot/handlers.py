from __future__ import annotations
import logging
import os
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile

from app.services.strict_parse import parse_strict_listing, ParseError
from app.db import session_scope
from app.repositories.listings import create_listing_from_parsed, list_recent_listings, delete_listing_by_id, get_all_listings, get_listings_filtered
from app.repositories.reminders import create_reminder, list_active_reminders, cancel_reminder
from app.services.export import export_listings_to_excel
from app.services.storage import save_bytes
from app.models.photos import Photo
from app.models.listings import Listing
from bot.state import set_attach_target, get_attach_target, pop_attach_target
import structlog
from app.repositories.audit import list_audit, log_event
from app.repositories.chat import add_message as chat_add, get_last_messages as chat_get_last
from app.services.ai_router import route_text_to_command
from app.schemas.listing_parse import ParsedListing, ListingType
from app.services.export import export_listings_to_excel, export_audit_to_excel, export_matches_to_excel
from app.services.export import import_listings_from_excel
from app.services.text_normalizer import normalize_contact
from app.config import get_settings
from app.repositories.access import create_token as access_create, revoke_token as access_revoke, list_tokens as access_list


logger = structlog.get_logger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
	settings = get_settings()
	return bool(settings.admin_chat_id) and settings.admin_chat_id == user_id


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
	await message.answer(
		"Здравствуйте! Доступные команды:\n"
		"/помощь — как правильно отправлять заявки\n"
		"/добавить <текст> — распознать и сохранить запись\n"
		"/прикрепить <id> — прикрепить фото к записи\n"
		"/список — последние записи\n"
		"/удалить <id> — удалить запись\n"
		"/экспорт [город] [тип] [мин_цена] [макс_цена] — экспорт в Excel\n"
		"/напомнить <дата время> <текст> — создать напоминание\n"
		"/диагностика — самодиагностика системы"
	)


# Русские алиасы команд (Telegram не распознаёт кириллицу как bot_command,
# поэтому ловим текстом и проксируем к исходным хэндлерам)
@router.message(F.text.casefold().in_({"/старт", "старт"}))
async def cmd_start_ru(message: Message) -> None:
	await cmd_start(message)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
	text = (
		"Команды\n\n"
		"1) Добавление (строго 7 полей)\n"
		"/добавить Наименование, Количество, Город, Имя, Телефон, Цена, Тип\n"
		"Пример: /добавить Фотоаппарат, 1, Рязань, Сергей, +7 999 1234567, 10000 руб, продажа\n\n"
		"2) Фото\n"
		"/прикрепить <id> — выбрать запись, затем отправьте одно/несколько фото сообщениями\n\n"
		"3) Управление\n"
		"/список — последние записи\n"
		"/удалить <id> — удалить запись\n"
		"/изменить <id> key=value [key=value ...] — обновить поля записи\n\n"
		"4) Экспорт\n"
		"/экспорт [город] [тип] [мин_цена] [макс_цена] — Excel в чат\n\n"
		"5) Совпадения\n"
		"/совпадения — расчёт совпадений и Excel-отчёт (по умолчанию: порог 0.45; веса — наименование 0.60, характеристики 0.20, город 0.15, цена 0.05; допуски цены — не заданы; порог нечёткого совпадения названия 0.60).\n"
		"Можно задать параметры: /совпадения <порог> <w_title> <w_char> <w_loc> <w_price> <абс_допуск_₽> <допуск_%> <fuzzy_порог>\n\n"
		"6) Напоминания\n"
		"/напомнить <дата время> <текст> — создать\n"
		"Форматы: HH:MM | dd.mm HH:MM | dd.mm.yy HH:MM | YYYY-MM-DD HH:MM | YYYY-MM-DDTHH:MM\n"
		"/напоминания — показать активные\n"
		"/отменить_напоминание <id> — отменить\n\n"
		"7) Веб-интерфейс\n"
		"/веб — ссылка на веб-приложение (список, детали, совпадения, журнал)\n\n"
		"8) Диагностика\n"
		"/диагностика — самодиагностика системы\n\n"
		"Документы\n"
		"Отправьте Excel (.xlsx) того же формата, что экспорт — бот объединит данные с текущей базой.\n"
	)
	await message.answer(text)


@router.message(F.text.casefold().in_({"/помощь", "помощь"}))
async def cmd_help_ru(message: Message) -> None:
	await cmd_help(message)


# Алиасы для команд с параметрами — используем startswith, чтобы передавать аргументы как есть
@router.message(F.text.casefold().startswith("/добавить"))
async def cmd_add_ru_slash(message: Message) -> None:
	await cmd_add(message)


@router.message(F.text.casefold().startswith("добавить"))
async def cmd_add_ru(message: Message) -> None:
	await cmd_add(message)


@router.message(F.text.casefold().startswith("/прикрепить"))
async def cmd_attach_ru_slash(message: Message) -> None:
	await cmd_attach(message)


@router.message(F.text.casefold().startswith("прикрепить"))
async def cmd_attach_ru(message: Message) -> None:
	await cmd_attach(message)


@router.message(F.text.casefold().in_({"/список", "список"}))
async def cmd_list_ru(message: Message) -> None:
	await cmd_list(message)


@router.message(F.text.casefold().in_({"/показать", "показать"}))
async def cmd_list_ru2(message: Message) -> None:
	await cmd_list(message)


@router.message(F.text.casefold().in_({"/записи", "записи"}))
async def cmd_list_ru3(message: Message) -> None:
	await cmd_list(message)


@router.message(F.text.casefold().startswith("/удалить"))
async def cmd_delete_ru_slash(message: Message) -> None:
	await cmd_delete(message)


@router.message(F.text.casefold().startswith("удалить"))
async def cmd_delete_ru(message: Message) -> None:
	await cmd_delete(message)


@router.message(F.text.casefold().startswith("/экспорт"))
async def cmd_export_ru_slash(message: Message) -> None:
	await cmd_export(message)


@router.message(F.text.casefold().startswith("экспорт"))
async def cmd_export_ru(message: Message) -> None:
	await cmd_export(message)


@router.message(F.text.casefold().startswith("/напомнить"))
async def cmd_remind_ru_slash(message: Message) -> None:
	await cmd_remind(message)


@router.message(F.text.casefold().startswith("напомнить"))
async def cmd_remind_ru(message: Message) -> None:
	await cmd_remind(message)


@router.message(F.text.casefold().in_({"/напоминания", "напоминания"}))
async def cmd_reminders_ru(message: Message) -> None:
	await cmd_reminders(message)


@router.message(F.text.casefold().in_({"/мои_напоминания", "мои напоминания"}))
async def cmd_reminders_ru2(message: Message) -> None:
	await cmd_reminders(message)


@router.message(F.text.casefold().in_({"/активные_напоминания", "активные напоминания"}))
async def cmd_reminders_ru3(message: Message) -> None:
	await cmd_reminders(message)


@router.message(F.text.casefold().startswith("/отменить_напоминание"))
async def cmd_cancel_reminder_ru1_slash(message: Message) -> None:
	await cmd_cancel_reminder(message)


@router.message(F.text.casefold().startswith("отменить_напоминание"))
async def cmd_cancel_reminder_ru1(message: Message) -> None:
	await cmd_cancel_reminder(message)


@router.message(F.text.casefold().startswith("/отмена_напоминания"))
async def cmd_cancel_reminder_ru2_slash(message: Message) -> None:
	await cmd_cancel_reminder(message)


@router.message(F.text.casefold().startswith("отмена_напоминания"))
async def cmd_cancel_reminder_ru2(message: Message) -> None:
	await cmd_cancel_reminder(message)


@router.message(F.text.casefold().in_({"/самодиагностика", "самодиагностика"}))
async def cmd_diagnose_ru(message: Message) -> None:
	await cmd_diagnose(message)


@router.message(F.text.casefold().in_({"/журнал", "журнал"}))
async def cmd_audit_ru(message: Message) -> None:
	await cmd_audit(message)


@router.message(F.text.casefold().in_({"/веб", "веб"}))
async def cmd_web_ru(message: Message) -> None:
	await cmd_web(message)


@router.message(F.text.casefold().in_({"/ктоя", "ктоя", "кто я"}))
async def cmd_whoami_ru(message: Message) -> None:
	await cmd_whoami(message)


@router.message(F.text.casefold().startswith("/изменить"))
async def cmd_edit_ru_slash(message: Message) -> None:
	await cmd_edit(message)


@router.message(F.text.casefold().startswith("изменить"))
async def cmd_edit_ru(message: Message) -> None:
	await cmd_edit(message)


@router.message(F.text.casefold().startswith("/выдать_токен"))
async def cmd_grant_ru_slash(message: Message) -> None:
	await cmd_grant(message)


@router.message(F.text.casefold().startswith("выдать_токен"))
async def cmd_grant_ru(message: Message) -> None:
	await cmd_grant(message)


@router.message(F.text.casefold().startswith("/отозвать_токен"))
async def cmd_revoke_ru_slash(message: Message) -> None:
	await cmd_revoke(message)


@router.message(F.text.casefold().startswith("отозвать_токен"))
async def cmd_revoke_ru(message: Message) -> None:
	await cmd_revoke(message)


@router.message(F.text.casefold().in_({"/токены", "токены"}))
async def cmd_tokens_ru(message: Message) -> None:
	await cmd_tokens(message)


# Добавляем недостающие алиасы для команд, которые работают только со слешем
@router.message(F.text.casefold().in_({"/помощь", "помощь"}))
async def cmd_help_ru(message: Message) -> None:
	await cmd_help(message)


@router.message(F.text.casefold().in_({"/справка", "справка"}))
async def cmd_help_ru2(message: Message) -> None:
	await cmd_help(message)


@router.message(F.text.casefold().in_({"/что_умеешь", "что умеешь", "что умеешь?"}))
async def cmd_help_ru3(message: Message) -> None:
	await cmd_help(message)


@router.message(F.text.casefold().in_({"/какие_команды", "какие команды", "какие команды?"}))
async def cmd_help_ru4(message: Message) -> None:
	await cmd_help(message)


@router.message(F.text.casefold().in_({"/импорт", "импорт"}))
async def cmd_import_ru(message: Message) -> None:
	await message.answer("Чтобы импортировать, отправьте Excel-файл (.xlsx) в чат — я его загружу и объединю с базой.")


@router.message(F.text.casefold().in_({"/редактировать", "редактировать"}))
async def cmd_edit_ru2(message: Message) -> None:
	await cmd_edit(message)


@router.message(F.text.casefold().in_({"/обновить", "обновить"}))
async def cmd_edit_ru3(message: Message) -> None:
	await cmd_edit(message)


@router.message(F.text.casefold().in_({"/создать_токен", "создать токен"}))
async def cmd_grant_ru2(message: Message) -> None:
	await cmd_grant(message)


@router.message(F.text.casefold().in_({"/убрать_токен", "убрать токен"}))
async def cmd_revoke_ru2(message: Message) -> None:
	await cmd_revoke(message)


@router.message(F.text.casefold().in_({"/показать_токены", "показать токены"}))
async def cmd_tokens_ru2(message: Message) -> None:
	await cmd_tokens(message)


@router.message(F.text.casefold().in_({"/проверить", "проверить"}))
async def cmd_diagnose_ru2(message: Message) -> None:
	await cmd_diagnose(message)


@router.message(F.text.casefold().in_({"/статус", "статус"}))
async def cmd_diagnose_ru3(message: Message) -> None:
	await cmd_diagnose(message)


@router.message(F.text.casefold().in_({"/логи", "логи"}))
async def cmd_audit_ru2(message: Message) -> None:
	await cmd_audit(message)


@router.message(F.text.casefold().in_({"/история", "история"}))
async def cmd_audit_ru3(message: Message) -> None:
	await cmd_audit(message)


@router.message(F.text.casefold().in_({"/сайт", "сайт"}))
async def cmd_web_ru2(message: Message) -> None:
	await cmd_web(message)


@router.message(F.text.casefold().in_({"/ссылка", "ссылка"}))
async def cmd_web_ru3(message: Message) -> None:
	await cmd_web(message)


@router.message(F.text.casefold().in_({"/мой_id", "мой id", "мой id?"}))
async def cmd_whoami_ru2(message: Message) -> None:
	await cmd_whoami(message)


@router.message(F.text.casefold().in_({"/кто_я", "кто я", "кто я?"}))
async def cmd_whoami_ru3(message: Message) -> None:
	await cmd_whoami(message)


@router.message(F.text.casefold().in_({"/информация", "информация"}))
async def cmd_whoami_ru4(message: Message) -> None:
	await cmd_whoami(message)


# Восстанавливаем недостающие команды
@router.message(Command("audit"))
async def cmd_audit(message: Message) -> None:
	# Формат: /audit [YYYY-MM-DD] [YYYY-MM-DD]
	text = (message.text or "").strip()
	parts = text.split()
	date_from = None
	date_to = None
	from datetime import datetime
	if len(parts) >= 2:
		try:
			date_from = datetime.strptime(parts[1], "%Y-%m-%d")
		except Exception:
			date_from = None
	if len(parts) >= 3:
		try:
			date_to = datetime.strptime(parts[2], "%Y-%m-%d")
		except Exception:
			date_to = None
	with session_scope() as session:
		rows = list_audit(session, date_from=date_from, date_to=date_to)
	if not rows:
		await message.answer("Журнал пуст за указанный период.")
		return
	from datetime import datetime as _dt
	from pathlib import Path
			stamp = _dt.now(ZoneInfo("Asia/Tashkent")).strftime("%Y%m%d_%H%M%S")
	out_path = Path.cwd() / f"audit_{stamp}.xlsx"
	export_audit_to_excel(rows, out_path)
	try:
		await message.answer_document(FSInputFile(path=out_path), caption=f"Журнал: {len(rows)} записей")
	finally:
		try:
			out_path.unlink(missing_ok=True)
		except Exception:
			pass


# Алиасы для команды аудита с параметрами
@router.message(F.text.casefold().startswith("журнал "))
async def cmd_audit_ru_with_params(message: Message) -> None:
	await cmd_audit(message)


@router.message(F.text.casefold().startswith("/журнал "))
async def cmd_audit_ru_slash_with_params(message: Message) -> None:
	await cmd_audit(message)


@router.message(F.text.casefold().startswith("логи "))
async def cmd_audit_ru2_with_params(message: Message) -> None:
	await cmd_audit(message)


@router.message(F.text.casefold().startswith("/логи "))
async def cmd_audit_ru2_slash_with_params(message: Message) -> None:
	await cmd_audit(message)


@router.message(F.text.casefold().startswith("история "))
async def cmd_audit_ru3_with_params(message: Message) -> None:
	await cmd_audit(message)


@router.message(F.text.casefold().startswith("/история "))
async def cmd_audit_ru3_slash_with_params(message: Message) -> None:
	await cmd_audit(message)


@router.message(Command("web"))
async def cmd_web(message: Message) -> None:
	settings = get_settings()
	base = settings.web_base_url.strip() if settings.web_base_url else None
	if not base:
		# Сформируем локальный URL
		base = f"http://localhost:{settings.app_port}"
	await message.answer(f"Веб-интерфейс: {base}/web/")


# Алиасы для команды веб-интерфейса
@router.message(F.text.casefold().in_({"/сайт", "сайт"}))
async def cmd_web_ru2(message: Message) -> None:
	await cmd_web(message)


@router.message(F.text.casefold().in_({"/ссылка", "ссылка"}))
async def cmd_web_ru3(message: Message) -> None:
	await cmd_web(message)


@router.message(F.text.casefold().in_({"/браузер", "браузер"}))
async def cmd_web_ru4(message: Message) -> None:
	await cmd_web(message)


@router.message(Command("edit"))
async def cmd_edit(message: Message) -> None:
	# Формат: /edit <id> key=value [key=value ...]
	text = (message.text or "").strip()
	parts = text.split(maxsplit=2)
	if len(parts) < 3:
		await message.answer("Использование: /edit <id> key=value [key=value ...]. Пример: /edit 7 title=Новый price=120000 location=Москва")
		return
	try:
		listing_id = int(parts[1])
	except Exception:
		await message.answer("ID должен быть числом.")
		return
	pairs_raw = parts[2]
	# Разбор key=value, поддержим значения в кавычках
	import shlex
	try:
		tokens = shlex.split(pairs_raw)
	except Exception:
		tokens = pairs_raw.split()
	updates: dict[str, str] = {}
	for tok in tokens:
		if "=" not in tok:
			continue
		k, v = tok.split("=", 1)
		k = k.strip().lower()
		v = v.strip()
		updates[k] = v
	if not updates:
		await message.answer("Нет полей для обновления. Разрешены: title, description, characteristics, quantity, price, location, contact, type")
		return
	allowed = {"title", "description", "characteristics", "quantity", "price", "location", "contact", "type"}
	with session_scope() as session:
		item = session.get(Listing, listing_id)
		if not item:
			await message.answer("Запись не найдена")
			return
		changed: list[str] = []
		if "title" in updates:
			item.title = updates["title"]
			changed.append("title")
		if "description" in updates:
			item.description = updates["description"]
			changed.append("description")
		if "characteristics" in updates:
			import json as _json
			try:
				item.characteristics = _json.loads(updates["characteristics"]) if updates["characteristics"] else None
			except Exception:
				await message.answer("characteristics: ожидается JSON")
				return
			changed.append("characteristics")
		if "quantity" in updates:
			try:
				item.quantity = int(updates["quantity"]) if updates["quantity"] != "" else None
			except Exception:
				await message.answer("quantity: ожидается целое число")
				return
			changed.append("quantity")
		if "price" in updates:
			from decimal import Decimal as _Dec
			try:
				val = updates["price"].replace(" ", "")
				item.price = _Dec(val) if val != "" else None
			except Exception:
				await message.answer("price: ожидается число")
				return
			changed.append("price")
		if "location" in updates:
			item.location = updates["location"] or None
			changed.append("location")
		if "contact" in updates:
			item.contact = normalize_contact(updates["contact"]) if updates["contact"] else None
			changed.append("contact")
		if "type" in updates:
			item.type = updates["type"] or item.type
			changed.append("type")
		# аудит
		from app.repositories.audit import log_event as _log
		_log(session, action="update", resource="listing", actor=str(message.from_user.id), payload={"listing_id": item.id, "changed": changed})
	await message.answer(f"Обновлено #{listing_id}: {', '.join(changed) if changed else 'без изменений'}")


# Алиасы для команды редактирования с параметрами
@router.message(F.text.casefold().startswith("изменить "))
async def cmd_edit_ru_with_params(message: Message) -> None:
	await cmd_edit(message)


@router.message(F.text.casefold().startswith("/изменить "))
async def cmd_edit_ru_slash_with_params(message: Message) -> None:
	await cmd_edit(message)


@router.message(F.text.casefold().startswith("редактировать "))
async def cmd_edit_ru2_with_params(message: Message) -> None:
	await cmd_edit(message)


@router.message(F.text.casefold().startswith("/редактировать "))
async def cmd_edit_ru2_slash_with_params(message: Message) -> None:
	await cmd_edit(message)


@router.message(F.text.casefold().startswith("обновить "))
async def cmd_edit_ru3_with_params(message: Message) -> None:
	await cmd_edit(message)


@router.message(F.text.casefold().startswith("/обновить "))
async def cmd_edit_ru3_slash_with_params(message: Message) -> None:
	await cmd_edit(message)


@router.message(Command("grant"))
async def cmd_grant(message: Message) -> None:
	if not _is_admin(message.from_user.id):
		await message.answer("Команда доступна только администратору.")
		return
	# /grant <minutes> — создать токен на N минут (или без срока при 0/пропуске)
	parts = (message.text or "").strip().split()
	expire_minutes = None
	if len(parts) >= 2:
		try:
			expire_minutes = int(parts[1])
		except Exception:
			expire_minutes = None
	from datetime import datetime, timedelta
	expires_at = None
	if expire_minutes and expire_minutes > 0:
		expires_at = datetime.now(ZoneInfo("Asia/Tashkent")) + timedelta(minutes=expire_minutes)
	with session_scope() as session:
		t = access_create(session, expires_at)
	settings = get_settings()
	base = settings.web_base_url.strip() if settings.web_base_url else f"http://localhost:{settings.app_port}"
	await message.answer(f"Токен создан:\n{t.token}\n\nСсылка: {base}/web/?token={t.token}\nИстекает: {t.expires_at or 'без срока'}")


# Алиасы для команды выдачи токенов с параметрами
@router.message(F.text.casefold().startswith("выдать_токен "))
async def cmd_grant_ru_with_params(message: Message) -> None:
	await cmd_grant(message)


@router.message(F.text.casefold().startswith("/выдать_токен "))
async def cmd_grant_ru_slash_with_params(message: Message) -> None:
	await cmd_grant(message)


@router.message(F.text.casefold().startswith("создать_токен "))
async def cmd_grant_ru2_with_params(message: Message) -> None:
	await cmd_grant(message)


@router.message(F.text.casefold().startswith("/создать_токен "))
async def cmd_grant_ru2_slash_with_params(message: Message) -> None:
	await cmd_grant(message)


@router.message(Command("revoke"))
async def cmd_revoke(message: Message) -> None:
	if not _is_admin(message.from_user.id):
		await message.answer("Команда доступна только администратору.")
		return
	# /revoke <token>
	parts = (message.text or "").strip().split(maxsplit=1)
	if len(parts) < 2:
		await message.answer("Использование: /revoke <token>")
		return
	value = parts[1].strip()
	with session_scope() as session:
		ok = access_revoke(session, value)
	await message.answer("Отозвано" if ok else "Токен не найден")


# Алиасы для команды отзыва токенов с параметрами
@router.message(F.text.casefold().startswith("отозвать_токен "))
async def cmd_revoke_ru_with_params(message: Message) -> None:
	await cmd_revoke(message)


@router.message(F.text.casefold().startswith("/отозвать_токен "))
async def cmd_revoke_ru_slash_with_params(message: Message) -> None:
	await cmd_revoke(message)


@router.message(F.text.casefold().startswith("убрать_токен "))
async def cmd_revoke_ru2_with_params(message: Message) -> None:
	await cmd_revoke(message)


@router.message(F.text.casefold().startswith("/убрать_токен "))
async def cmd_revoke_ru2_slash_with_params(message: Message) -> None:
	await cmd_revoke(message)


# Алиасы для команды добавления с параметрами
@router.message(F.text.casefold().startswith("добавить "))
async def cmd_add_ru_with_params(message: Message) -> None:
	await cmd_add(message)


@router.message(F.text.casefold().startswith("/добавить "))
async def cmd_add_ru_slash_with_params(message: Message) -> None:
	await cmd_add(message)


# Добавляем недостающие команды
@router.message(Command("add"))
async def cmd_add(message: Message) -> None:
	text = (message.text or "").strip()
	parts = text.split(maxsplit=1)
	if len(parts) < 2 or not parts[1].strip():
		await message.answer("Использование (строго): /добавить Наименование, Количество, Город, Имя, Телефон, Цена, Тип")
		return

	payload = parts[1].strip()
	logger.info("cmd_add_received", user_id=message.from_user.id, text=payload)
	try:
		parsed = parse_strict_listing(payload)
		with session_scope() as session:
			listing = create_listing_from_parsed(session, parsed)
			# audit
			log_event(session, action="create", resource="listing", actor=str(message.from_user.id), payload={"listing_id": listing.id, "title": listing.title, "type": listing.type})
		logger.info("listing_created", listing_id=listing.id, title=listing.title, type=listing.type)
		await message.answer(
			f"Сохранено: id={listing.id}\n"
			f"Наименование: {listing.title}\n"
			f"Тип: {listing.type}\n"
			f"Город: {listing.location or '-'}\n"
			f"Цена: {listing.price or '-'}\n\n"
			f"Чтобы прикрепить фото, отправьте: /прикрепить {listing.id}"
		)
	except ParseError as pe:
		await message.answer(f"Ошибка формата: {pe}\n\nФормат: /добавить Наименование, Количество, Город, Имя, Телефон, Цена, Тип\nПример: /добавить Фотоаппарат, 1, Рязань, Сергей, +7 999 1234567, 10000 руб, продажа")
	except Exception as exc:
		logger.error("cmd_add_failed", error=str(exc))
		await message.answer(f"Ошибка: {exc}")


@router.message(Command("attach"))
async def cmd_attach(message: Message) -> None:
	text = (message.text or "").strip()
	parts = text.split(maxsplit=1)
	if len(parts) < 2:
		await message.answer("Использование: /прикрепить <id>")
		return
	try:
		listing_id = int(parts[1])
	except Exception:
		await message.answer("ID должен быть числом.")
		return
	set_attach_target(message.from_user.id, listing_id)
	logger.info("attach_mode_set", user_id=message.from_user.id, listing_id=listing_id)
	await message.answer("Ок, пришлите фото сообщением(ями). Когда закончите — отправьте любую команду.")


# Алиасы для команды прикрепления фото с параметрами
@router.message(F.text.casefold().startswith("прикрепить "))
async def cmd_attach_ru_with_params(message: Message) -> None:
	await cmd_attach(message)


@router.message(F.text.casefold().startswith("/прикрепить "))
async def cmd_attach_ru_slash_with_params(message: Message) -> None:
	await cmd_attach(message)


@router.message(Command("list"))
async def cmd_list(message: Message) -> None:
	limit = 10
	with session_scope() as session:
		items = list_recent_listings(session, limit=limit)
	if not items:
		await message.answer("Записей пока нет.")
		return
	lines = ["Последние записи:"]
	for it in items:
		lines.append(f"#{it.id}: {it.title} | {it.type} | {it.location or '-'} | {it.price or '-'}")
	await message.answer("\n".join(lines))


# Алиасы для команды списка
@router.message(F.text.casefold().in_({"/список", "список"}))
async def cmd_list_ru(message: Message) -> None:
	await cmd_list(message)


@router.message(F.text.casefold().in_({"/показать", "показать"}))
async def cmd_list_ru2(message: Message) -> None:
	await cmd_list(message)


@router.message(F.text.casefold().in_({"/записи", "записи"}))
async def cmd_list_ru3(message: Message) -> None:
	await cmd_list(message)


@router.message(Command("delete"))
async def cmd_delete(message: Message) -> None:
	text = (message.text or "").strip()
	parts = text.split(maxsplit=1)
	if len(parts) < 2:
		await message.answer("Использование: /удалить <id>")
		return
	try:
		listing_id = int(parts[1])
	except Exception:
		await message.answer("ID должен быть числом.")
		return
	with session_scope() as session:
		ok = delete_listing_by_id(session, listing_id)
		if ok:
			log_event(session, action="delete", resource="listing", actor=str(message.from_user.id), payload={"listing_id": listing_id})
	logger.info("listing_deleted", listing_id=listing_id, deleted=ok)
	await message.answer("Удалено" if ok else "Запись не найдена")


# Алиасы для команды удаления с параметрами
@router.message(F.text.casefold().startswith("удалить "))
async def cmd_delete_ru_with_params(message: Message) -> None:
	await cmd_delete(message)


@router.message(F.text.casefold().startswith("/удалить "))
async def cmd_delete_ru_slash_with_params(message: Message) -> None:
	await cmd_delete(message)


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
	text = (message.text or "").strip()
	parts = text.split()
	city = None
	listing_type = None
	price_min = None
	price_max = None
	if len(parts) >= 2:
		city = parts[1] if parts[1] != '-' else None
	if len(parts) >= 3:
		listing_type = parts[2] if parts[2] in {"sale", "demand", "contract"} else None
	if len(parts) >= 4:
		try:
			price_min = Decimal(parts[3])
		except Exception:
			price_min = None
	if len(parts) >= 5:
		try:
			price_max = Decimal(parts[4])
		except Exception:
			price_max = None

	with session_scope() as session:
		items = get_listings_filtered(session, city=city, listing_type=listing_type, price_min=price_min, price_max=price_max)
		ids = [it.id for it in items]
		photos_map = {}
		if ids:
			for p in session.query(Photo).filter(Photo.listing_id.in_(ids)).all():
				photos_map.setdefault(p.listing_id, []).append(p.url)
	if not items:
		await message.answer("Нет данных по заданным фильтрам.")
		return
	stamp = datetime.now(ZoneInfo("Asia/Tashkent")).strftime("%Y%m%d_%H%M%S")
	filename = f"export_{stamp}.xlsx"
	out_path = Path.cwd() / filename
	logger.info("export_started", count=len(items), city=city, type=listing_type, price_min=str(price_min) if price_min else None, price_max=str(price_max) if price_max else None)
	export_listings_to_excel(items, out_path, listing_id_to_photos=photos_map)
	try:
		await message.answer_document(FSInputFile(path=out_path), caption=f"Экспорт: {len(items)} записей")
	finally:
		try:
			out_path.unlink(missing_ok=True)
			logger.info("export_file_deleted", path=str(out_path))
		except Exception as exc:
			logger.warning("export_file_delete_failed", path=str(out_path), error=str(exc))


# Алиасы для команды экспорта с параметрами
@router.message(F.text.casefold().startswith("экспорт "))
async def cmd_export_ru_with_params(message: Message) -> None:
	await cmd_export(message)


@router.message(F.text.casefold().startswith("/экспорт "))
async def cmd_export_ru_slash_with_params(message: Message) -> None:
	await cmd_export(message)


@router.message(Command("matches"))
async def cmd_matches(message: Message) -> None:
    # Формат: /matches [порог] [w_title] [w_char] [w_loc] [w_price] [abs] [pct] [fuzzy]
    # Русские алиасы перехватываются ниже
    parts = (message.text or "").strip().split()
    def _f(i: int, default: float | None) -> float | None:
        try:
            return float(parts[i].replace(",", ".")) if len(parts) > i else default
        except Exception:
            return default
    threshold = _f(1, 0.45) or 0.45
    w_title = _f(2, 0.60) or 0.60
    w_char = _f(3, 0.20) or 0.20
    w_loc = _f(4, 0.15) or 0.15
    w_price = _f(5, 0.05) or 0.05
    abs_tol = _f(6, None)
    pct_tol = _f(7, None)
    fuzzy_thr = _f(8, 0.60) or 0.60

    from app.services.matching import group_listings, find_matches
    with session_scope() as session:
        items = get_all_listings(session)
    demands, sales = group_listings(items)
    from decimal import Decimal as _Dec
    pairs = find_matches(
        demands,
        sales,
        threshold=threshold,
        w_title=w_title,
        w_char=w_char,
        w_loc=w_loc,
        w_price=w_price,
        price_tolerance_abs=_Dec(abs_tol) if abs_tol is not None else None,
        price_tolerance_pct=pct_tol,
        fuzzy_token_threshold=fuzzy_thr,
    )
    if not pairs:
        await message.answer("Совпадений не найдено по заданным параметрам.")
        return
    from datetime import datetime as _dt
    from pathlib import Path as _Path
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
    	out = _Path.cwd() / f"matches_{_dt.now(ZoneInfo('Asia/Tashkent')).strftime('%Y%m%d_%H%M%S')}.xlsx"
    export_matches_to_excel(rows, out)
    try:
        await message.answer_document(FSInputFile(path=out), caption=f"Совпадения: {len(rows)} пар")
    finally:
        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass


# Алиасы для команды совпадений с параметрами
@router.message(F.text.casefold().startswith("совпадения "))
async def cmd_matches_ru_with_params(message: Message) -> None:
    await cmd_matches(message)


@router.message(F.text.casefold().startswith("/совпадения "))
async def cmd_matches_ru_slash_with_params(message: Message) -> None:
    await cmd_matches(message)


@router.message(Command("remind"))
async def cmd_remind(message: Message) -> None:
	text = (message.text or "").strip()
	parts = text.split(maxsplit=2)
	if len(parts) < 2:
		await message.answer("Использование: /напомнить <дата время> <текст>")
		return
	# Отделим дату+время от текста гибко
	tokens = text.split()
	if len(tokens) < 2:
		await message.answer("Использование: /напомнить <дата время> <текст>")
		return
	# Сценарии: HH:MM | dd.mm HH:MM | dd.mm.yy HH:MM | YYYY-MM-DD HH:MM | YYYY-MM-DDTHH:MM
	def parse_when(tokens: list[str]) -> tuple[datetime | None, int]:
		# Возвращает (when, consumed_tokens_after_command)
		from app.config import get_settings as _get_settings3
		from zoneinfo import ZoneInfo as _ZI3
		tz = _ZI3(_get_settings3().timezone)
		now = datetime.now(tz)
		# 1) HH:MM
		m = re.fullmatch(r"(\d{1,2}):(\d{2})", tokens[1]) if len(tokens) >= 2 else None
		if m and len(tokens) >= 3:  # требуется ещё хотя бы одно слово текста после времени
			h, mm = int(m.group(1)), int(m.group(2))
			try:
				return datetime(now.year, now.month, now.day, h, mm), 1
			except Exception:
				return None, 0
		# 2) dd.mm HH:MM
		if len(tokens) >= 3 and re.fullmatch(r"\d{1,2}\.\d{1,2}", tokens[1]) and re.fullmatch(r"\d{1,2}:\d{2}", tokens[2]):
			d, mo = map(int, tokens[1].split("."))
			h, mm = map(int, tokens[2].split(":"))
			try:
				return datetime(now.year, mo, d, h, mm), 2
			except Exception:
				return None, 0
		# 3) dd.mm.yy HH:MM
		if len(tokens) >= 3 and re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2}", tokens[1]) and re.fullmatch(r"\d{1,2}:\d{2}", tokens[2]):
			d, mo, yy = tokens[1].split(".")
			d, mo, yy = int(d), int(mo), int(yy)
			yyyy = 2000 + yy
			h, mm = map(int, tokens[2].split(":"))
			try:
				return datetime(yyyy, mo, d, h, mm), 2
			except Exception:
				return None, 0
		# 4) YYYY-MM-DDTHH:MM | YYYY-MM-DD HH:MM (одно токен-значение)
		if len(tokens) >= 2:
			cand = tokens[1].replace("T", " ")
			try:
				when = datetime.strptime(cand, "%Y-%m-%d %H:%M")
				return when, 1
			except Exception:
				pass
		return None, 0

	when, consumed = parse_when(tokens)
	if when is None or consumed == 0:
		await message.answer("Неверный формат даты/времени. Примеры: /напомнить 21.08 20:19 текст | /напомнить 21.08.25 20:19 текст | /напомнить 20:19 текст")
		return
	# Остальной текст после потребленных токенов (учитываем, что tokens[0] = /напомнить)
	msg_tokens = tokens[1 + consumed:]
	msg_text = " ".join(msg_tokens).strip()
	if not msg_text:
		await message.answer("Добавьте текст напоминания после даты и времени")
		return
	with session_scope() as session:
		rem = create_reminder(session, text=msg_text, remind_at=when, user_id=message.from_user.id)
	await message.answer(f"Напоминание создано: id={rem.id}, на {when.strftime('%Y-%m-%d %H:%M')}")


# Алиасы для команды напоминаний с параметрами
@router.message(F.text.casefold().startswith("напомнить "))
async def cmd_remind_ru_with_params(message: Message) -> None:
	await cmd_remind(message)


@router.message(F.text.casefold().startswith("/напомнить "))
async def cmd_remind_ru_slash_with_params(message: Message) -> None:
	await cmd_remind(message)


@router.message(Command("reminders"))
async def cmd_reminders(message: Message) -> None:
	with session_scope() as session:
		items = list_active_reminders(session)
	if not items:
		await message.answer("Активных напоминаний нет.")
		return
	lines = ["Активные напоминания:"]
	for r in items:
		lines.append(f"#{r.id}: {r.text} — {r.remind_at}")
	await message.answer("\n".join(lines))


# Алиасы для команды напоминаний
@router.message(F.text.casefold().in_({"/напоминания", "напоминания"}))
async def cmd_reminders_ru(message: Message) -> None:
	await cmd_reminders(message)


@router.message(F.text.casefold().in_({"/мои_напоминания", "мои напоминания"}))
async def cmd_reminders_ru2(message: Message) -> None:
	await cmd_reminders(message)


@router.message(F.text.casefold().in_({"/активные_напоминания", "активные напоминания"}))
async def cmd_reminders_ru3(message: Message) -> None:
	await cmd_reminders(message)


@router.message(Command("cancel_reminder"))
async def cmd_cancel_reminder(message: Message) -> None:
	text = (message.text or "").strip()
	parts = text.split(maxsplit=1)
	if len(parts) < 2:
		await message.answer("Использование: /отменить_напоминание <id>")
		return
	try:
		rid = int(parts[1])
	except Exception:
		await message.answer("ID должен быть числом.")
		return
	with session_scope() as session:
		ok = cancel_reminder(session, rid)
	await message.answer("Отменено" if ok else "Не найдено или уже отправлено")


# Алиасы для команды отмены напоминаний с параметрами
@router.message(F.text.casefold().startswith("отменить_напоминание "))
async def cmd_cancel_reminder_ru1_with_params(message: Message) -> None:
	await cmd_cancel_reminder(message)


@router.message(F.text.casefold().startswith("/отменить_напоминание "))
async def cmd_cancel_reminder_ru1_slash_with_params(message: Message) -> None:
	await cmd_cancel_reminder(message)


@router.message(F.text.casefold().startswith("отмена_напоминания "))
async def cmd_cancel_reminder_ru2_with_params(message: Message) -> None:
	await cmd_cancel_reminder(message)


@router.message(F.text.casefold().startswith("/отмена_напоминания "))
async def cmd_cancel_reminder_ru2_slash_with_params(message: Message) -> None:
	await cmd_cancel_reminder(message)


@router.message(Command("diagnose"))
async def cmd_diagnose(message: Message) -> None:
	from app.services.diagnostics import run_diagnostics
	with session_scope() as session:
		text, issues = run_diagnostics(session)
	# Телеграм ограничивает длину сообщения ~4К — порежем при необходимости
	if len(text) > 3500:
		text = text[:3500] + "\n... (обрезано)"
	await message.answer(text)


# Алиасы для команды диагностики
@router.message(F.text.casefold().in_({"/диагностика", "диагностика"}))
async def cmd_diagnose_ru(message: Message) -> None:
	await cmd_diagnose(message)


@router.message(F.text.casefold().in_({"/самодиагностика", "самодиагностика"}))
async def cmd_diagnose_ru2(message: Message) -> None:
	await cmd_diagnose(message)


@router.message(F.text.casefold().in_({"/проверить", "проверить"}))
async def cmd_diagnose_ru3(message: Message) -> None:
	await cmd_diagnose(message)


@router.message(F.text.casefold().in_({"/статус", "статус"}))
async def cmd_diagnose_ru4(message: Message) -> None:
	await cmd_diagnose(message)


@router.message(F.text.casefold().in_({"/здоровье", "здоровье"}))
async def cmd_diagnose_ru5(message: Message) -> None:
	await cmd_diagnose(message)


@router.message(Command("tokens"))
async def cmd_tokens(message: Message) -> None:
	if not _is_admin(message.from_user.id):
		await message.answer("Команда доступна только администратору.")
		return
	with session_scope() as session:
		items = access_list(session)
	if not items:
		await message.answer("Токенов нет")
		return
	lines = ["Токены:"]
	for t in items:
		lines.append(f"{t.id}. {t.token} — истекает: {t.expires_at or 'без срока'}")
	await message.answer("\n".join(lines))


# Алиасы для команды токенов
@router.message(F.text.casefold().in_({"/токены", "токены"}))
async def cmd_tokens_ru(message: Message) -> None:
	await cmd_tokens(message)


@router.message(F.text.casefold().in_({"/показать_токены", "показать токены"}))
async def cmd_tokens_ru2(message: Message) -> None:
	await cmd_tokens(message)


@router.message(F.text.casefold().in_({"/список_токенов", "список токенов"}))
async def cmd_tokens_ru3(message: Message) -> None:
	await cmd_tokens(message)


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
	uid = message.from_user.id
	uname = message.from_user.username or "-"
	await message.answer(f"Ваш Telegram ID: {uid}\nUsername: @{uname}")


# Обработка фото
@router.message(F.photo)
async def on_photo(message: Message) -> None:
	user_id = message.from_user.id
	target_id = get_attach_target(user_id)
	if not target_id:
		await message.answer("Сначала выберите запись командой /прикрепить <id>.")
		return
	photo = message.photo[-1]
	file = await message.bot.get_file(photo.file_id)
	file_bytes = await message.bot.download_file(file.file_path)
	content = file_bytes.getvalue()
	filename = f"{target_id}_{photo.file_unique_id}.jpg"
	key, url = save_bytes(filename, content)
	with session_scope() as session:
		p = Photo(listing_id=target_id, s3_key=key, url=url, size_bytes=len(content))
		session.add(p)
		listing = session.get(Listing, target_id)
		if listing is not None:
			links = list(listing.photo_links or [])
			if url not in links:
				links.append(url)
			listing.photo_links = links
			# audit
			log_event(session, action="attach_photo", resource="listing", actor=str(user_id), payload={"listing_id": target_id, "url": url})
		session.commit()
	logger.info("photo_attached", listing_id=target_id, url=url)
	await message.answer(f"Фото сохранено и привязано к записи #{target_id}. Ссылка: {url}")


# Импорт XLSX: ожидается файл того же формата, что экспорт
@router.message(F.document)
async def on_document(message: Message) -> None:
	try:
		doc = message.document
		if not doc or not (doc.file_name or '').lower().endswith('.xlsx'):
			return  # пропускаем не-Excel
		file = await message.bot.get_file(doc.file_id)
		file_bytes = await message.bot.download_file(file.file_path)
		from pathlib import Path as _Path
		tmp = _Path.cwd() / f"import_{doc.file_unique_id}.xlsx"
		tmp.write_bytes(file_bytes.getvalue())
		try:
			with session_scope() as session:
				n = import_listings_from_excel(session, tmp)
			await message.answer(f"Импорт завершён: обработано {n} строк.")
		finally:
			try:
				tmp.unlink(missing_ok=True)
			except Exception:
				pass
	except Exception as exc:
		await message.answer(f"Ошибка импорта: {exc}")


# ИИ-помощник: fallback на естественный язык, когда нет распознанной команды
@router.message(F.text & ~F.text.startswith("/"))
async def ai_fallback(message: Message) -> None:
	# Сохраняем сообщение пользователя
	with session_scope() as session:
		chat_add(session, message.from_user.id, "user", message.text or "")
		history = chat_get_last(session, message.from_user.id, limit=10)

	# Вызов LLM для выбора команды/аргументов/уточнения
	packed_history = [(m.role, m.text) for m in history]
	result = route_text_to_command(packed_history, message.text or "")
	if "error" in result:
		await message.answer("Не удалось обработать запрос ИИ. Попробуйте переформулировать.")
		return

	raw = (result.get("raw") or "").strip()
	if not raw:
		await message.answer("Не удалось понять запрос. Уточните, пожалуйста.")
		with session_scope() as s2:
			chat_add(s2, message.from_user.id, "assistant", "Не удалось понять запрос. Уточните, пожалуйста.")
		return

	# Пытаемся извлечь JSON (срезаем возможные код-блоки ```)
	import json as _json
	def _extract_json(txt: str):
		import re as _re
		m = _re.search(r"\{[\s\S]*\}$", txt)
		if m:
			return m.group(0)
		# уберём тройные кавычки и маркдауны
		txt = txt.strip().strip('`').strip()
		return txt
	jtxt = _extract_json(raw)
	try:
		data = _json.loads(jtxt)
	except Exception:
		await message.answer(raw[:1000])
		with session_scope() as s2:
			chat_add(s2, message.from_user.id, "assistant", raw[:1000])
		return

	command = (data.get("command") or "").strip().lower()
	args = data.get("args") or {}
	need_clarify = bool(data.get("need_clarify"))
	clarify = (data.get("clarify_question") or "").strip()
	if need_clarify and clarify:
		await message.answer(clarify)
		with session_scope() as s2:
			chat_add(s2, message.from_user.id, "assistant", clarify)
		return

	# Выполняем команду без модификации message.text
	try:
		if command == "list":
			await cmd_list(message)
		elif command == "help":
			await cmd_help(message)
		elif command == "web":
			await cmd_web(message)
		elif command == "reminders":
			await cmd_reminders(message)
		elif command == "import":
			await message.answer("Чтобы импортировать, отправьте Excel-файл (.xlsx) в чат — я его загружу и объединю с базой.")
		elif command == "delete":
			listing_id = int(args.get("id"))
			from app.repositories.listings import delete_listing_by_id
			with session_scope() as s2:
				ok = delete_listing_by_id(s2, listing_id)
			await message.answer("Удалено" if ok else "Запись не найдена")
		elif command == "attach":
			listing_id = int(args.get("id"))
			set_attach_target(message.from_user.id, listing_id)
			await message.answer("Ок, пришлите фото сообщением(ями). Когда закончите — отправьте любую команду.")
		elif command == "export":
			from app.repositories.listings import get_listings_filtered as _flt
			from app.models.photos import Photo as _Photo
			from app.services.export import export_listings_to_excel as _xlsx
			from decimal import Decimal as _Dec
			def _to_dec(v):
				if v is None or v == "":
					return None
				try:
					return _Dec(str(v).replace(" ", "").replace(",", "."))
				except Exception:
					return None
			city = args.get("city") or None
			ltype = args.get("type") or None
			pmin_d = _to_dec(args.get("price_min"))
			pmax_d = _to_dec(args.get("price_max"))
			with session_scope() as s2:
				items = _flt(s2, city=city, listing_type=ltype, price_min=pmin_d, price_max=pmax_d)
				ids = [it.id for it in items]
				photos_map = {}
				if ids:
					for p in s2.query(_Photo).filter(_Photo.listing_id.in_(ids)).all():
						photos_map.setdefault(p.listing_id, []).append(p.url)
			if not items:
				await message.answer("Нет данных по заданным фильтрам.")
			else:
				from datetime import datetime as _dt
				from pathlib import Path as _Path
				out = _Path.cwd() / f"export_{_dt.now(ZoneInfo('Asia/Tashkent')).strftime('%Y%m%d_%H%M%S')}.xlsx"
				_xlsx(items, out, listing_id_to_photos=photos_map)
				try:
					await message.answer_document(FSInputFile(path=out), caption=f"Экспорт: {len(items)} записей")
				finally:
					try:
						out.unlink(missing_ok=True)
					except Exception:
						pass
		elif command == "remind":
			# Парсинг относительных/абсолютных дат и создание напоминания напрямую
			from datetime import datetime as _dt, timedelta as _td
			import re as _re
			when_s = (args.get("when") or "").strip()
			text_body = (args.get("text") or "").strip()
			if not when_s or not text_body:
				await message.answer("Нужны дата/время и текст: /напомнить <дата время> <текст>")
			else:
				from app.config import get_settings as _get_settings
				from zoneinfo import ZoneInfo as _ZI
				tz = _ZI(_get_settings().timezone)
				now = _dt.now(tz)
				s = when_s.lower().strip()
				when_dt = None
				m = _re.fullmatch(r"сегодня\s*(в\s*)?(\d{1,2}:\d{2})", s)
				if m:
					h, mm = map(int, m.group(2).split(":"))
					try:
						when_dt = _dt(now.year, now.month, now.day, h, mm)
					except Exception:
						when_dt = None
				if when_dt is None:
					m = _re.fullmatch(r"завтра\s*(в\s*)?(\d{1,2}:\d{2})", s)
					if m:
						h, mm = map(int, m.group(2).split(":"))
						dt = now + _td(days=1)
						try:
							when_dt = _dt(dt.year, dt.month, dt.day, h, mm)
						except Exception:
							when_dt = None
				if when_dt is None:
					wdays = {"понедельник":0,"пн":0,"вторник":1,"вт":1,"среда":2,"ср":2,"четверг":3,"чт":3,"пятница":4,"пт":4,"суббота":5,"сб":5,"воскресенье":6,"вс":6}
					m = _re.fullmatch(r"(понедельник|пн|вторник|вт|среда|ср|четверг|чт|пятница|пт|суббота|сб|воскресенье|вс)\s*(в\s*)?(\d{1,2}:\d{2})", s)
					if m:
						wd = wdays[m.group(1)]
						h, mm = map(int, m.group(3).split(":"))
						delta = (wd - now.weekday()) % 7
						if delta == 0:
							candidate = _dt(now.year, now.month, now.day, h, mm)
							when_dt = candidate if candidate > now else candidate + _td(days=7)
						else:
							when_dt = (now + _td(days=delta)).replace(hour=h, minute=mm, second=0, microsecond=0)
				if when_dt is None:
					m = _re.fullmatch(r"(\d{1,2}):(\d{2})", s)
					if m:
						h, mm = int(m.group(1)), int(m.group(2))
						try:
							when_dt = _dt(now.year, now.month, now.day, h, mm)
						except Exception:
							when_dt = None
				if when_dt is None and _re.fullmatch(r"\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}", s):
					dmo, tpart = s.split()
					d, mo = map(int, dmo.split("."))
					h, mm = map(int, tpart.split(":"))
					try:
						when_dt = _dt(now.year, mo, d, h, mm)
					except Exception:
						when_dt = None
				if when_dt is None and _re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2}\s+\d{1,2}:\d{2}", s):
					dmo, tpart = s.split()
					d, mo, yy = dmo.split(".")
					d, mo, yy = int(d), int(mo), int(yy)
					yyyy = 2000 + yy
					h, mm = map(int, tpart.split(":"))
					try:
						when_dt = _dt(now.year, mo, d, h, mm)
					except Exception:
						when_dt = None
				if when_dt is None:
					cand = s.replace("T", " ")
					try:
						when_dt = _dt.strptime(cand, "%Y-%m-%d %H:%M")
					except Exception:
						when_dt = None
				# относительные выражения: через N минут/часов/дней/недель, через полчаса
				if when_dt is None:
					m2 = _re.fullmatch(r"через\s+(\d+)\s*(минут[уы]?|час(а|ов)?|дн(я|ей)?|недел(ю|и|ь))", s)
					if m2:
						n = int(m2.group(1))
						unit = m2.group(2)
						from datetime import timedelta as _td2
						if unit.startswith("минут"):
							when_dt = now + _td2(minutes=n)
						elif unit.startswith("час"):
							when_dt = _td2(hours=n)
						elif unit.startswith("дн"):
							when_dt = now + _td2(days=n)
						elif unit.startswith("недел"):
							when_dt = now + _td2(weeks=n)
				if when_dt is None and s == "через полчаса":
					from datetime import timedelta as _td3
					when_dt = now + _td3(minutes=30)
				if when_dt is None:
					await message.answer("Не удалось разобрать дату/время. Пример: сегодня 14:30, завтра 09:00, среда 10:15, 21.08 10:00, через 5 минут")
				else:
					with session_scope() as s2:
						rem = create_reminder(s2, text=text_body, remind_at=when_dt, user_id=message.from_user.id)
					await message.answer(f"Напоминание создано: id={rem.id}, на {when_dt.strftime('%Y-%m-%d %H:%M')}")
		elif command == "cancel_reminder":
			rid = int(args.get("id"))
			with session_scope() as s2:
				ok = cancel_reminder(s2, rid)
			await message.answer("Отменено" if ok else "Не найдено или уже отправлено")
		elif command == "edit":
			listing_id = int(args.get("id"))
			updates = args.get("updates") or {}
			with session_scope() as s2:
				item = s2.get(Listing, listing_id)
				if not item:
					await message.answer("Запись не найдена")
				else:
					changed = []
					if "title" in updates:
						item.title = updates["title"]
						changed.append("title")
					if "description" in updates:
						item.description = updates["description"]
						changed.append("description")
					if "characteristics" in updates:
						import json as _json2
						try:
							item.characteristics = _json2.loads(updates["characteristics"]) if updates["characteristics"] else None
						except Exception:
							await message.answer("characteristics: ожидается JSON")
							s2.rollback()
							return
						changed.append("characteristics")
					if "quantity" in updates:
						try:
							item.quantity = int(updates["quantity"]) if updates["quantity"] != "" else None
						except Exception:
							await message.answer("quantity: ожидается целое число")
							s2.rollback()
							return
						changed.append("quantity")
					if "price" in updates:
						from decimal import Decimal as _Dec2
						try:
							val = str(updates["price"]).replace(" ", "")
							item.price = _Dec2(val) if val != "" else None
						except Exception:
							await message.answer("price: ожидается число")
							s2.rollback()
							return
						changed.append("price")
					if "location" in updates:
						item.location = updates["location"] or None
						changed.append("location")
					if "contact" in updates:
						item.contact = normalize_contact(updates["contact"]) if updates["contact"] else None
						changed.append("contact")
					if "type" in updates:
						item.type = updates["type"] or item.type
						changed.append("type")
					from app.repositories.audit import log_event as _log
					_log(s2, action="update", resource="listing", actor=str(message.from_user.id), payload={"listing_id": item.id, "changed": changed})
					await message.answer(f"Обновлено #{listing_id}: {', '.join(changed) if changed else 'без изменений'}")
		elif command == "add":
			# Нормализация аргументов ИИ (русские синонимы и форматирование)
			def _map_type(v: str | None) -> ListingType | None:
				if not v:
					return None
				val = str(v).strip().lower()
				mapping = {
					"продажа": "sale",
					"продаю": "sale",
					"продать": "sale",
					"sale": "sale",
					"sell": "sale",
					"покупка": "demand",
					"куплю": "demand",
					"купить": "demand",
					"demand": "demand",
					"buy": "demand",
					"контракт": "contract",
					"договор": "contract",
					"contract": "contract",
				}
				val = mapping.get(val, val)
				try:
					return ListingType(val)
				except Exception:
					return None

			from decimal import Decimal as _Dec
			import re as _re
			def _to_decimal(v) -> _Dec | None:
				if v is None or v == "":
					return None
				if isinstance(v, (int, float)):
					return _Dec(str(v))
				s = str(v)
				s = s.replace(" ", "").replace("руб.", "").replace("руб","")
				s = s.replace(",", ".")
				s = _re.sub(r"[^0-9\.]", "", s)
				try:
					return _Dec(s) if s else None
				except Exception:
					return None

			def _to_int(v) -> int | None:
				if v is None or v == "":
					return None
				if isinstance(v, int):
					return v
				s = str(v).strip().lower()
				words1 = {"один","одна","one"}
				if s in words1:
					return 1
				m = _re.search(r"\d+", s)
				return int(m.group(0)) if m else None

			ptype = _map_type(args.get("type"))
			if ptype is None:
				await message.answer("Уточните тип: продажа/покупка/контракт")
				with session_scope() as s2:
					chat_add(s2, message.from_user.id, "assistant", "Уточните тип: продажа/покупка/контракт")
				return

			# Подстраховка извлечения из исходного текста
			original_text = (message.text or "").strip()
			title_val = (args.get("title") or args.get("name"))
			if not title_val:
				# Попробуем взять всё до первой запятой как наименование
				hdr = original_text.split(",", 1)[0].strip()
				if hdr:
					title_val = hdr
				else:
					await message.answer("Уточните наименование (что именно?): например, \"Фонарик\"")
					with session_scope() as s2:
						chat_add(s2, message.from_user.id, "assistant", "Уточните наименование (что именно?)")
					return

			# Извлечение города, если отсутствует
			location_val = args.get("location")
			if not location_val and original_text:
				import re as _re2
				m = _re2.search(r"(?:город|г\.|г\s)\s*([^,]+)", original_text, flags=_re2.IGNORECASE)
				if m:
					location_val = m.group(1).strip()

			pl = ParsedListing(
				title=title_val,
				description=args.get("description"),
				characteristics=args.get("characteristics"),
				quantity=_to_int(args.get("quantity")),
				price=_to_decimal(args.get("price")),
				location=location_val or args.get("location"),
				contact=normalize_contact(args.get("contact")) if args.get("contact") else None,
				photo_links=args.get("photo_links"),
				type=ptype,
			)
			with session_scope() as s2:
				listing = create_listing_from_parsed(s2, pl)
				log_event(s2, action="create", resource="listing", actor=str(message.from_user.id), payload={"listing_id": listing.id, "title": listing.title, "type": listing.type})
			await message.answer(
				f"Сохранено: id={listing.id}\n"
				f"Наименование: {listing.title}\n"
				f"Тип: {listing.type}\n"
				f"Город: {listing.location or '-'}\n"
				f"Цена: {listing.price or '-'}\n\n"
				f"Чтобы прикрепить фото, отправьте: /прикрепить {listing.id}"
			)
		else:
			await message.answer("Не удалось подобрать действие. Попробуйте сформулировать иначе.")
	except Exception as exc:
		await message.answer(f"Ошибка выполнения: {exc}")

	# Сохраняем ответ ассистента в историю
	with session_scope() as session:
		chat_add(session, message.from_user.id, "assistant", "(команда выполнена)")


# Алиасы для команды идентификации
@router.message(F.text.casefold().in_({"/ктоя", "ктоя", "кто я"}))
async def cmd_whoami_ru(message: Message) -> None:
	await cmd_whoami(message)


@router.message(F.text.casefold().in_({"/мой_id", "мой id", "мой id?"}))
async def cmd_whoami_ru2(message: Message) -> None:
	await cmd_whoami(message)


@router.message(F.text.casefold().in_({"/кто_я", "кто я", "кто я?"}))
async def cmd_whoami_ru3(message: Message) -> None:
	await cmd_whoami(message)


@router.message(F.text.casefold().in_({"/информация", "информация"}))
async def cmd_whoami_ru4(message: Message) -> None:
	await cmd_whoami(message)


# Алиасы для команды выдачи токенов с параметрами
@router.message(F.text.casefold().startswith("выдать_токен "))
async def cmd_grant_ru_with_params(message: Message) -> None:
	await cmd_grant(message)


@router.message(F.text.casefold().startswith("/выдать_токен "))
async def cmd_grant_ru_slash_with_params(message: Message) -> None:
	await cmd_grant(message)


@router.message(F.text.casefold().startswith("создать_токен "))
async def cmd_grant_ru2_with_params(message: Message) -> None:
	await cmd_grant(message)


@router.message(F.text.casefold().startswith("/создать_токен "))
async def cmd_grant_ru2_slash_with_params(message: Message) -> None:
	await cmd_grant(message)


# Алиасы для команды отзыва токенов с параметрами
@router.message(F.text.casefold().startswith("отозвать_токен "))
async def cmd_revoke_ru_with_params(message: Message) -> None:
	await cmd_revoke(message)


@router.message(F.text.casefold().startswith("/отозвать_токен "))
async def cmd_revoke_ru_slash_with_params(message: Message) -> None:
	await cmd_revoke(message)


@router.message(F.text.casefold().startswith("убрать_токен "))
async def cmd_revoke_ru2_with_params(message: Message) -> None:
	await cmd_revoke(message)


@router.message(F.text.casefold().startswith("/убрать_токен "))
async def cmd_revoke_ru2_slash_with_params(message: Message) -> None:
	await cmd_revoke(message)