from __future__ import annotations
import os
from pathlib import Path
from typing import Tuple

import boto3
import structlog

from app.config import get_settings


logger = structlog.get_logger(__name__)


def _project_root() -> Path:
	# Файл находится в AI_DB/app/services/storage.py → корень проекта = parents[2]
	return Path(__file__).resolve().parents[2]


def _resolve_upload_dir(raw_dir: str | None) -> Path:
	if not raw_dir:
		raw_dir = "uploads"
	p = Path(raw_dir)
	if p.is_absolute():
		return p
	# относительный путь якорим на корень проекта (не на CWD)
	return _project_root() / p


def get_upload_dir() -> Path:
	"""Путь к каталогу загрузок. Гарантирует его существование."""
	upload_dir = _resolve_upload_dir(get_settings().upload_dir)
	upload_dir.mkdir(parents=True, exist_ok=True)
	return upload_dir


def _ensure_upload_dir() -> Path:
	upload_dir = get_upload_dir()
	logger.info("upload_dir_ready", upload_dir=str(upload_dir), cwd=str(Path.cwd()))
	return upload_dir


def save_bytes(filename: str, content: bytes) -> Tuple[str, str]:
	"""Сохраняет контент. Возвращает (storage_key, url)."""
	settings = get_settings()
	if settings.s3_endpoint_url and settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key:
		s3 = boto3.client(
			"s3",
			endpoint_url=settings.s3_endpoint_url,
			aws_access_key_id=settings.s3_access_key_id,
			aws_secret_access_key=settings.s3_secret_access_key,
			region_name=settings.s3_region,
		)
		key = f"uploads/{filename}"
		s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=content, ContentType="image/jpeg")
		url = f"{settings.s3_endpoint_url}/{settings.s3_bucket}/{key}"
		logger.info("photo_saved_s3", key=key, url=url, size=len(content))
		return key, url
	# Fallback — локально
	upload_dir = _ensure_upload_dir()
	path = upload_dir / filename
	path.write_bytes(content)
	# Возвращаем HTTP URL для веб-интерфейса
	url = f"/uploads/{filename}"
	logger.info("photo_saved_local", path=str(path), url=url, size=len(content))
	return str(path), url