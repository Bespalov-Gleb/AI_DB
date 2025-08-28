from __future__ import annotations
import logging
import os
import sys
from typing import Any

import structlog


def setup_logging() -> None:
	level_name = os.getenv("LOG_LEVEL", "INFO").upper()
	level = getattr(logging, level_name, logging.INFO)
	log_file = os.getenv("LOG_FILE")

	handlers = [logging.StreamHandler(sys.stdout)]
	if log_file:
		# Создадим папку, если нужно
		os.makedirs(os.path.dirname(log_file), exist_ok=True)
		handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

	logging.basicConfig(
		level=level,
		handlers=handlers,
		format="%(message)s",
	)

	structlog.configure(
		processors=[
			structlog.processors.TimeStamper(fmt="ISO"),
			structlog.stdlib.add_log_level,
			structlog.stdlib.add_logger_name,
			structlog.processors.StackInfoRenderer(),
			structlog.processors.format_exc_info,
			structlog.processors.UnicodeDecoder(),
			structlog.processors.JSONRenderer(),
		],
		logger_factory=structlog.stdlib.LoggerFactory(),
		wrapper_class=structlog.stdlib.BoundLogger,
		cache_logger_on_first_use=True,
	)