import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import create_database_schema
from app.routers.health import router as health_router
from app.routers.ai import router as ai_router
from app.routers.web import router as web_router
from app.scheduler import start_scheduler
from app.logging_config import setup_logging
from app.services.storage import get_upload_dir
import structlog


setup_logging()
logger = structlog.get_logger(__name__)

app = FastAPI(title="AI DB Service")


@app.on_event("startup")
def on_startup() -> None:
	create_database_schema()
	start_scheduler()
	logger.info("app_started", status="startup_completed")


# Static and uploads
app.mount("/uploads", StaticFiles(directory=str(get_upload_dir())), name="uploads")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(ai_router, prefix="/ai", tags=["ai"])
app.include_router(web_router, prefix="/web", tags=["web"])