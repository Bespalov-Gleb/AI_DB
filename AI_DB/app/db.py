from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from app.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session, future=True)
Base = declarative_base()


def create_database_schema() -> None:
    # Импортировать модели перед созданием таблиц
    from app.models import users, listings, photos, reminders, audit_log  # noqa: F401
    from app.models import chat_messages  # noqa: F401
    from app.models import access_tokens  # noqa: F401
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()