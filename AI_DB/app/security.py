from __future__ import annotations
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings
from app.db import session_scope
from app.repositories.access import get_token


basic = HTTPBasic()


def require_web_access(request: Request, creds: Optional[HTTPBasicCredentials] = Depends(basic)) -> None:
	settings = get_settings()
	# 1) basic-admin
	if creds is not None and creds.username == settings.admin_username and creds.password == settings.admin_password:
		return
	# 2) guest token in query (?token=...)
	token = request.query_params.get("token")
	if token:
		with session_scope() as session:
			entry = get_token(session, token)
			if entry and (entry.expires_at is None or entry.expires_at > datetime.now(ZoneInfo("Europe/Moscow"))):
				return
	raise HTTPException(status_code=401, detail="Unauthorized")