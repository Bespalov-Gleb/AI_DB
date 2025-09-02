from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
import os
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

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
	logger.info("daily_matches_job_started")
	settings = get_settings()
	if not settings.telegram_bot_token or not settings.admin_chat_id:
		logger.warning("daily_matches_job_skipped", reason="missing_telegram_config", has_token=bool(settings.telegram_bot_token), has_chat_id=bool(settings.admin_chat_id))
		return
	with session_scope() as session:
		items: List[Listing] = get_all_listings(session)
	demands, sales = group_listings(items)
	pairs = find_matches(demands, sales)
	if not pairs:
		return
	stamp = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y%m%d_%H%M%S')
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
	caption = f"Найдено совпадений: {len(rows)}"
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
	logger.info("weekly_backup_job_started")
	settings = get_settings()
	if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
		logger.warning("weekly_backup_job_skipped", reason="missing_smtp_config", has_host=bool(settings.smtp_host), has_username=bool(settings.smtp_username), has_password=bool(settings.smtp_password))
		return
	with session_scope() as session:
		items: List[Listing] = get_all_listings(session)
	if not items:
		logger.info("weekly_backup_job_skipped", reason="no_data")
		return
	stamp = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y%m%d_%H%M%S')
	out_path = Path.cwd() / f"backup_{stamp}.xlsx"
	export_listings_to_excel(items, out_path)
	try:
		send_email(subject="Weekly DB backup", body=f"Backup at {stamp}", attachments=[out_path])
		logger.info("weekly_backup_job_completed", items_count=len(items), sent_to=settings.smtp_to)
	finally:
		try:
			out_path.unlink(missing_ok=True)
		except Exception:
			pass


def weekly_stats_job() -> None:
	logger.info("weekly_stats_job_started")
	settings = get_settings()
	if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
		logger.warning("weekly_stats_job_skipped", reason="missing_smtp_config", has_host=bool(settings.smtp_host), has_username=bool(settings.smtp_username), has_password=bool(settings.smtp_password))
		return
	with session_scope() as session:
		items: List[Listing] = get_all_listings(session)
	stamp = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y%m%d_%H%M%S')
	out_path = Path.cwd() / f"stats_{stamp}.xlsx"
	export_stats_to_excel(items, out_path)
	try:
		send_email(subject="Weekly stats", body=f"Stats at {stamp}", attachments=[out_path])
		logger.info("weekly_stats_job_completed", items_count=len(items), sent_to=settings.smtp_to)
	finally:
		try:
			out_path.unlink(missing_ok=True)
		except Exception:
			pass


async def reminders_tick_job() -> None:
	settings = get_settings()
	if not settings.telegram_bot_token or not settings.admin_chat_id:
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
			await bot.send_message(chat_id=target_chat, text=f"Напоминание #{r.id}: {r.text}")
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
	settings = get_settings()
	if not settings.telegram_bot_token or not settings.admin_chat_id:
		return
	with session_scope() as session:
		text, _ = run_diagnostics(session)
	bot = Bot(token=settings.telegram_bot_token)
	try:
		await bot.send_message(chat_id=settings.admin_chat_id, text=text[:4000])
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
	if _scheduler is not None:
		return
	settings = get_settings()
	tz = ZoneInfo(settings.timezone)
	_scheduler = AsyncIOScheduler(timezone=tz)
	
	# Добавляем задачи с логированием
	logger.info("scheduler_setup_start", timezone=str(tz))
	
	_scheduler.add_job(daily_matches_job, trigger='cron', hour=9, minute=0, id='daily_matches')
	logger.info("scheduler_job_added", job_id='daily_matches', schedule='9:00 daily')
	
	_scheduler.add_job(weekly_backup_job, trigger='cron', day_of_week='fri', hour=17, minute=0, id='weekly_backup')
	logger.info("scheduler_job_added", job_id='weekly_backup', schedule='Friday 17:00')
	
	_scheduler.add_job(weekly_stats_job, trigger='cron', day_of_week='mon', hour=9, minute=0, id='weekly_stats')
	logger.info("scheduler_job_added", job_id='weekly_stats', schedule='Monday 9:00')
	
	_scheduler.add_job(reminders_tick_job, trigger='cron', second='0', id='reminders_tick')
	logger.info("scheduler_job_added", job_id='reminders_tick', schedule='every second')
	
	_scheduler.add_job(weekly_diagnostics_job, trigger='cron', day_of_week='wed', hour=18, minute=0, id='weekly_diagnostics')
	logger.info("scheduler_job_added", job_id='weekly_diagnostics', schedule='Wednesday 18:00')
	
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