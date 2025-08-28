from __future__ import annotations
import mimetypes
import os
import smtplib
from email.message import EmailMessage
import ssl
from pathlib import Path
from typing import Iterable, List

import structlog

from app.config import get_settings
import socket


logger = structlog.get_logger(__name__)


def _parse_recipients(value: str | None) -> List[str]:
	if not value:
		return []
	parts = [p.strip() for p in value.split(",") if p.strip()]
	return parts


def send_email(subject: str, body: str, attachments: Iterable[Path] | None = None) -> None:
	settings = get_settings()
	recipients = _parse_recipients(settings.smtp_to)
	if not (settings.smtp_host and settings.smtp_port and settings.smtp_username and settings.smtp_password and settings.smtp_from and recipients):
		raise RuntimeError("SMTP settings are incomplete or no recipients configured")

	msg = EmailMessage()
	msg["Subject"] = subject
	msg["From"] = settings.smtp_from
	msg["To"] = ", ".join(recipients)
	msg.set_content(body or "")

	for path in (attachments or []):
		p = Path(path)
		if not p.exists():
			logger.warning("email_attachment_missing", path=str(p))
			continue
		mime, _ = mimetypes.guess_type(p.name)
		maintype, subtype = (mime.split("/", 1) if mime else ("application", "octet-stream"))
		msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)

	# Попытка 1: использовать порт из настроек (587 STARTTLS или 465 SMTPS)
	context = ssl.create_default_context()
	try:
		port = int(settings.smtp_port)
		if port == 465:
			with smtplib.SMTP_SSL(settings.smtp_host, port, timeout=20, context=context) as server:
				server.login(settings.smtp_username, settings.smtp_password)
				server.send_message(msg)
		else:
			with smtplib.SMTP(settings.smtp_host, port, timeout=20) as server:
				server.ehlo()
				server.starttls(context=context)
				server.ehlo()
				server.login(settings.smtp_username, settings.smtp_password)
				server.send_message(msg)
		logger.info("email_sent", subject=subject, to=recipients, attachments=[str(Path(a)) for a in (attachments or [])])
		return
	except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, socket.timeout, ConnectionError) as e:
		logger.warning("email_send_primary_failed", error=str(e), host=settings.smtp_host, port=settings.smtp_port)
		# Попытка 2: резервный SMTPS на 465
		try:
			with smtplib.SMTP_SSL(settings.smtp_host, 465, timeout=20, context=context) as server:
				server.login(settings.smtp_username, settings.smtp_password)
				server.send_message(msg)
			logger.info("email_sent", subject=subject, to=recipients, attachments=[str(Path(a)) for a in (attachments or [])], mode="fallback_ssl_465")
			return
		except Exception as e2:
			logger.error("email_send_failed", error=str(e2))
			raise