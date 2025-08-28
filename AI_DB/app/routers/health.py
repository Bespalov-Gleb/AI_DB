from fastapi import APIRouter
from sqlalchemy import text

from app.db import session_scope

router = APIRouter()


@router.get("/", summary="Health check")
def health() -> dict:
    return {"status": "ok"}


@router.get("/db", summary="Database connectivity check")
def health_db() -> dict:
    with session_scope() as session:
        session.execute(text("SELECT 1"))
    return {"db": "ok"}