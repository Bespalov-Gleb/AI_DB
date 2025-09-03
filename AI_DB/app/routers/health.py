from fastapi import APIRouter
from sqlalchemy import text

from app.db import session_scope
from app.scheduler import _scheduler, daily_matches_job, weekly_backup_job, weekly_stats_job, weekly_diagnostics_job
from app.config import get_settings
from datetime import datetime
from zoneinfo import ZoneInfo

router = APIRouter()


@router.get("/", summary="Health check")
def health() -> dict:
    return {"status": "ok"}


@router.get("/db", summary="Database connectivity check")
def health_db() -> dict:
    with session_scope() as session:
        session.execute(text("SELECT 1"))
    return {"db": "ok"}


@router.get("/scheduler", summary="Scheduler status check")
def health_scheduler() -> dict:
    if _scheduler is None:
        return {"scheduler": "not_started"}
    
    jobs = _scheduler.get_jobs()
    return {
        "scheduler": "running",
        "job_count": len(jobs),
        "jobs": [
            {
                "id": job.id,
                "name": job.name,
                "trigger": str(job.trigger),
                "next_run_time": str(job.next_run_time) if job.next_run_time else None
            }
            for job in jobs
        ]
    }


@router.post("/scheduler/test", summary="Test scheduler jobs manually")
async def test_scheduler_jobs() -> dict:
    """Принудительно запускает все задачи планировщика для тестирования"""
    if _scheduler is None:
        return {"error": "Scheduler not started"}
    
    results = {}
    
    # Тестируем Telegram задачи
    try:
        await daily_matches_job()
        results["daily_matches"] = "completed"
    except Exception as e:
        results["daily_matches"] = f"error: {str(e)}"
    
    try:
        await weekly_diagnostics_job()
        results["weekly_diagnostics"] = "completed"
    except Exception as e:
        results["weekly_diagnostics"] = f"error: {str(e)}"
    
    # Тестируем Email задачи
    try:
        weekly_backup_job()
        results["weekly_backup"] = "completed"
    except Exception as e:
        results["weekly_backup"] = f"error: {str(e)}"
    
    try:
        weekly_stats_job()
        results["weekly_stats"] = "completed"
    except Exception as e:
        results["weekly_stats"] = f"error: {str(e)}"
    
    return {"test_results": results}


@router.get("/time", summary="Current time and timezone info")
def health_time() -> dict:
    """Показывает текущее время и настройки таймзоны"""
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    
    return {
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": settings.timezone,
        "timezone_offset": now.strftime("%z"),
        "utc_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": now.strftime("%A"),
        "weekday_ru": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][now.weekday()]
    }