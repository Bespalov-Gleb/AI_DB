from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
import os
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

# ВНИМАНИЕ: ТЕСТОВОЕ РАСПИСАНИЕ
# Все задачи запускаются по средам в 20:15-20:18 (UTC+5) для удобства тестирования
# После тестирования вернуть на обычное расписание:
# - daily_matches: ежедневно в 9:00
# - weekly_backup: по пятницам в 17:00  
# - weekly_stats: по понедельникам в 9:00
# - weekly_diagnostics: по средам в 18:00

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.db import session_scope
from app.models.listings import Listing
from app.repositories.listings import get_all_listings
from app.repositories.reminders import list_active_reminders, mark_sent
from app.services.matching import group_listings, find_matches
from app.services.export import export_matches_to_excel, export_listings_to_excel, export_stats_to_excel
from app.services.emailer import send_email
from app.services.diagnostics import run_diagnostics
from app.repositories.audit import log_event
import structlog


_scheduler: AsyncIOScheduler | None = None
logger = structlog.get_logger(__name__)


async def _send_document(bot: Bot, chat_id: int, filepath: Path, caption: str) -> None:
	with filepath.open('rb') as fp:
		await bot.send_document(chat_id=chat_id, document=fp, caption=caption)


async def daily_matches_job() -> None:
	"""Задача поиска совпадений - запускается по средам в 20:15 (UTC+5)"""
	logger.info("daily_matches_job_started")
	settings = get_settings()
	logger.info("daily_matches_job_settings", has_token=bool(settings.telegram_bot_token), has_chat_id=bool(settings.admin_chat_id), timezone=settings.timezone)
	if not settings.telegram_bot_token or not settings.admin_chat_id:
		logger.warning("daily_matches_job_skipped", reason="missing_telegram_config", has_token=bool(settings.telegram_bot_token), has_chat_id=bool(settings.admin_chat_id))
		return
	with session_scope() as session:
		items: List[Listing] = get_all_listings(session)
	
	if not items:
		# Отправляем сообщение о том, что данных нет
		bot = Bot(token=settings.telegram_bot_token)
		try:
			await bot.send_message(chat_id=settings.admin_chat_id, text="📊 Данных для анализа совпадений нет")
			logger.info("daily_matches_job_completed", pairs_count=0, sent_to=settings.admin_chat_id, reason="no_data")
		finally:
			await bot.session.close()
		return
	
	demands, sales = group_listings(items)
	pairs = find_matches(demands, sales)
	if not pairs:
		# Отправляем сообщение о том, что совпадений не найдено
		bot = Bot(token=settings.telegram_bot_token)
		try:
			await bot.send_message(chat_id=settings.admin_chat_id, text="🔍 Совпадений не найдено")
			logger.info("daily_matches_job_completed", pairs_count=0, sent_to=settings.admin_chat_id)
		finally:
			await bot.session.close()
		return
		now = datetime.now(ZoneInfo(settings.timezone))
	stamp = now.strftime('%Y%m%d_%H%M%S')
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
	filename = f"matches_{stamp}.xlsx"
	out_path = Path.cwd() / filename
	export_matches_to_excel(rows, out_path)
	bot = Bot(token=settings.telegram_bot_token)
	caption = f"🔍 Найдено совпадений: {len(rows)}\n📅 Дата: {now.strftime('%Y-%m-%d %H:%M')} (UTC+5)\n📊 Всего записей в БД: {len(items)}"
	try:
		await _send_document(bot, settings.admin_chat_id, out_path, caption)
		logger.info("daily_matches_job_completed", pairs_count=len(rows), sent_to=settings.admin_chat_id)
	finally:
		try:
			out_path.unlink(missing_ok=True)
		except Exception:
			pass
	await bot.session.close()


def weekly_backup_job() -> None:
	"""Задача создания бэкапа - запускается по средам в 20:16 (UTC+5)"""
	logger.info("weekly_backup_job_started")
	settings = get_settings()
	logger.info("weekly_backup_job_settings", has_host=bool(settings.smtp_host), has_username=bool(settings.smtp_username), has_password=bool(settings.smtp_password), smtp_to=settings.smtp_to)
	if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
		logger.warning("weekly_backup_job_skipped", reason="missing_smtp_config", has_host=bool(settings.smtp_host), has_username=bool(settings.smtp_username), has_password=bool(settings.smtp_password))
		return
	with session_scope() as session:
		items: List[Listing] = get_all_listings(session)
	if not items:
		logger.info("weekly_backup_job_skipped", reason="no_data")
		# Отправляем email о том, что данных для бэкапа нет
		try:
			now = datetime.now(ZoneInfo(settings.timezone))
			send_email(subject="Weekly DB backup - No data", body=f"Backup skipped at {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC+5)\nNo data available\nTimezone: {settings.timezone}")
			logger.info("weekly_backup_job_completed", items_count=0, sent_to=settings.smtp_to)
		except Exception as e:
			logger.error("weekly_backup_job_email_failed", error=str(e))
		return
	now = datetime.now(ZoneInfo(settings.timezone))
	stamp = now.strftime('%Y%m%d_%H%M%S')
	out_path = Path.cwd() / f"backup_{stamp}.xlsx"
	export_listings_to_excel(items, out_path)
	try:
		subject = f"Weekly DB backup - {len(items)} items"
		body = f"Backup at {stamp} (UTC+5)\nTotal items: {len(items)}\nTimezone: {settings.timezone}\nGenerated: {now.strftime('%Y-%m-%d %H:%M:%S')}"
		send_email(subject=subject, body=body, attachments=[out_path])
		logger.info("weekly_backup_job_completed", items_count=len(items), sent_to=settings.smtp_to)
	finally:
		try:
			out_path.unlink(missing_ok=True)
		except Exception:
			pass


def weekly_stats_job() -> None:
	"""Задача создания статистики - запускается по средам в 20:17 (UTC+5)"""
	logger.info("weekly_stats_job_started")
	settings = get_settings()
	logger.info("weekly_stats_job_settings", has_host=bool(settings.smtp_host), has_username=bool(settings.smtp_username), has_password=bool(settings.smtp_password), smtp_to=settings.smtp_to)
	if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
		logger.warning("weekly_stats_job_skipped", reason="missing_smtp_config", has_host=bool(settings.smtp_host), has_username=bool(settings.smtp_username), has_password=bool(settings.smtp_password))
		return
	with session_scope() as session:
		items: List[Listing] = get_all_listings(session)
	
	# Всегда отправляем статистику, даже если данных нет
	now = datetime.now(ZoneInfo(settings.timezone))
	stamp = now.strftime('%Y%m%d_%H%M%S')
	out_path = Path.cwd() / f"stats_{stamp}.xlsx"
	export_stats_to_excel(items, out_path)
	try:
		subject = f"Weekly stats - {len(items)} items"
		body = f"Stats at {stamp} (UTC+5)\nTotal items: {len(items)}\nTimezone: {settings.timezone}\nGenerated: {now.strftime('%Y-%m-%d %H:%M:%S')}"
		send_email(subject=subject, body=body, attachments=[out_path])
		logger.info("weekly_stats_job_completed", items_count=len(items), sent_to=settings.smtp_to)
	finally:
		try:
			out_path.unlink(missing_ok=True)
		except Exception:
			pass


async def reminders_tick_job() -> None:
	logger.info("reminders_tick_job_started")
	settings = get_settings()
	logger.info("reminders_tick_job_settings", has_token=bool(settings.telegram_bot_token), has_chat_id=bool(settings.admin_chat_id))
	if not settings.telegram_bot_token or not settings.admin_chat_id:
		logger.warning("reminders_tick_job_skipped", reason="missing_telegram_config", has_token=bool(settings.telegram_bot_token), has_chat_id=bool(settings.admin_chat_id))
		return
	tz = ZoneInfo(settings.timezone)
	now = datetime.now(tz)
	with session_scope() as session:
		reminders = list_active_reminders(session)
		to_send = []
		for r in reminders:
			ra = r.remind_at
			if ra is None:
				continue
			# Приводим naive к локальной тайзоне
			if ra.tzinfo is None:
				ra = ra.replace(tzinfo=tz)
			if ra <= now and not r.is_sent:
				to_send.append(r)
	if not to_send:
		return
	logger.info("reminders_due", count=len(to_send), now=str(now))
	bot = Bot(token=settings.telegram_bot_token)
	for r in to_send:
		try:
			target_chat = r.user_id or settings.admin_chat_id
			if not target_chat:
				continue
			logger.info("reminder_sending", reminder_id=r.id, to=int(target_chat))
			now = datetime.now(ZoneInfo(settings.timezone))
			message = f"⏰ Напоминание #{r.id}\n📝 {r.text}\n🕐 Время: {now.strftime('%H:%M:%S')} (UTC+5)"
			await bot.send_message(chat_id=target_chat, text=message)
			with session_scope() as session:
				mark_sent(session, r.id)
				log_event(session, action="reminder_sent", resource="reminder", actor=str(target_chat), payload={"reminder_id": r.id, "text": r.text})
		except Exception as exc:
			logger.warning("reminder_send_failed", reminder_id=r.id, error=str(exc))
	await bot.session.close()
	# Удалим отправленные напоминания старше 1 дня
	from datetime import timedelta as _td
	with session_scope() as session:
		from app.repositories.reminders import delete_sent_before as _del_old
		cutoff = now - _td(days=1)
		_del_old(session, cutoff)


async def weekly_diagnostics_job() -> None:
	"""Задача диагностики - запускается по средам в 20:18 (UTC+5)"""
	logger.info("weekly_diagnostics_job_started")
	settings = get_settings()
	logger.info("weekly_diagnostics_job_settings", has_token=bool(settings.telegram_bot_token), has_chat_id=bool(settings.admin_chat_id))
	if not settings.telegram_bot_token or not settings.admin_chat_id:
		logger.warning("weekly_diagnostics_job_skipped", reason="missing_telegram_config", has_token=bool(settings.telegram_bot_token), has_chat_id=bool(settings.admin_chat_id))
		return
	with session_scope() as session:
		text, _ = run_diagnostics(session)
	
	# Добавляем информацию о времени выполнения
	now = datetime.now(ZoneInfo(settings.timezone))
	header = f"📊 Диагностика за {now.strftime('%Y-%m-%d %H:%M')} (UTC+5)\n\n"
	full_text = header + text
	
	bot = Bot(token=settings.telegram_bot_token)
	try:
		# Разбиваем на части, если текст слишком длинный
		if len(full_text) > 4000:
			parts = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
			for i, part in enumerate(parts):
				await bot.send_message(chat_id=settings.admin_chat_id, text=f"Часть {i+1}/{len(parts)}:\n{part}")
		else:
			await bot.send_message(chat_id=settings.admin_chat_id, text=full_text)
		logger.info("weekly_diagnostics_job_completed", text_length=len(full_text), sent_to=settings.admin_chat_id)
	finally:
		await bot.session.close()


async def test_message_job() -> None:
	"""Тестовая задача: отправляет сообщение 'ТЕСТ' каждую минуту"""
	logger.info("test_message_job_started")
	settings = get_settings()
	logger.info("test_message_job_settings", has_token=bool(settings.telegram_bot_token), has_chat_id=bool(settings.admin_chat_id))
	if not settings.telegram_bot_token or not settings.admin_chat_id:
		logger.warning("test_message_job_skipped", reason="missing_telegram_config", has_token=bool(settings.telegram_bot_token), has_chat_id=bool(settings.admin_chat_id))
		return
	
	bot = Bot(token=settings.telegram_bot_token)
	try:
		now = datetime.now(ZoneInfo(settings.timezone))
		message = f"🧪 ТЕСТ - {now.strftime('%H:%M:%S')} (UTC+5)\n📊 Планировщик работает корректно!"
		await bot.send_message(chat_id=settings.admin_chat_id, text=message)
		logger.info("test_message_job_completed", message=message, sent_to=settings.admin_chat_id)
	finally:
		await bot.session.close()



def friday_test_report_job() -> None:
	settings = get_settings()
	with session_scope() as session:
		items: List[Listing] = get_all_listings(session)
	stamp = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y%m%d_%H%M%S')
	out_path = Path.cwd() / f"test_report_{stamp}.xlsx"
	export_stats_to_excel(items, out_path)
	try:
		send_email(subject="Тестовый отчёт", body=f"Тестовый отчёт сгенерирован {stamp}", attachments=[out_path])
	finally:
		try:
			out_path.unlink(missing_ok=True)
		except Exception:
			pass


def start_scheduler() -> None:
	global _scheduler
	logger.info("start_scheduler_called")
	if _scheduler is not None:
		logger.info("scheduler_already_running")
		return
	settings = get_settings()
	logger.info("start_scheduler_settings", timezone=settings.timezone, has_telegram=bool(settings.telegram_bot_token), has_admin=bool(settings.admin_chat_id), has_smtp=bool(settings.smtp_host))
	tz = ZoneInfo(settings.timezone)
	_scheduler = AsyncIOScheduler(timezone=tz)
	
	# Добавляем задачи с логированием (ТЕСТОВОЕ РАСПИСАНИЕ - по средам)
	logger.info("scheduler_setup_start", timezone=str(tz))
	
	_scheduler.add_job(daily_matches_job, trigger='cron', day_of_week='wed', hour=20, minute=15, id='daily_matches')
	logger.info("scheduler_job_added", job_id='daily_matches', schedule='Wednesday 20:15 (TEST)')
	
	_scheduler.add_job(weekly_backup_job, trigger='cron', day_of_week='wed', hour=20, minute=16, id='weekly_backup')
	logger.info("scheduler_job_added", job_id='weekly_backup', schedule='Wednesday 20:16 (TEST)')
	
	_scheduler.add_job(weekly_stats_job, trigger='cron', day_of_week='wed', hour=20, minute=17, id='weekly_stats')
	logger.info("scheduler_job_added", job_id='weekly_stats', schedule='Wednesday 20:17 (TEST)')
	
	_scheduler.add_job(reminders_tick_job, trigger='cron', second='0', id='reminders_tick')
	logger.info("scheduler_job_added", job_id='reminders_tick', schedule='every second')
	
	_scheduler.add_job(weekly_diagnostics_job, trigger='cron', day_of_week='wed', hour=20, minute=18, id='weekly_diagnostics')
	logger.info("scheduler_job_added", job_id='weekly_diagnostics', schedule='Wednesday 20:18 (TEST)')
	
	# Тестовая задача: отправляет сообщение 'ТЕСТ' каждую минуту (ОТКЛЮЧЕНО)
	# _scheduler.add_job(test_message_job, trigger='cron', minute='*', id='test_message')
	# logger.info("scheduler_job_added", job_id='test_message', schedule='every minute')
	
	# Опциональный разовый тест-старт: запускает тестовый отчёт через 1 минуту после старта
	if os.getenv("TEST_EMAIL_ONCE", "0") == "1":
		_scheduler.add_job(friday_test_report_job, trigger='date', run_date=datetime.now(tz) + timedelta(minutes=1), id='test_email_report_once', replace_existing=True)
		logger.info("scheduler_test_job_added", job_id='test_email_report_once', schedule='1 minute from start')
	
	# Тест планировщика: запускает все задачи через 2 минуты после старта
	if os.getenv("TEST_SCHEDULER_ONCE", "0") == "1":
		test_time = datetime.now(tz) + timedelta(minutes=2)
		_scheduler.add_job(daily_matches_job, trigger='date', run_date=test_time, id='test_daily_matches', replace_existing=True)
		_scheduler.add_job(weekly_backup_job, trigger='date', run_date=test_time, id='test_weekly_backup', replace_existing=True)
		_scheduler.add_job(weekly_stats_job, trigger='date', run_date=test_time, id='test_weekly_stats', replace_existing=True)
		_scheduler.add_job(weekly_diagnostics_job, trigger='date', run_date=test_time, id='test_weekly_diagnostics', replace_existing=True)
		logger.info("scheduler_test_jobs_added", test_time=str(test_time))
	
	_scheduler.start()
	logger.info("scheduler_started", job_count=len(_scheduler.get_jobs()), timezone=str(tz))
	
	# Проверяем, что задачи действительно добавлены
	all_jobs = _scheduler.get_jobs()
	logger.info("scheduler_jobs_verification", total_jobs=len(all_jobs))
	for job in all_jobs:
		logger.info("scheduler_job_details", id=job.id, name=job.name, trigger=str(job.trigger), next_run=str(job.next_run_time))