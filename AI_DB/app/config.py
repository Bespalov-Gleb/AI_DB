import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
	app_env: str = os.getenv("APP_ENV", "local")
	app_host: str = os.getenv("APP_HOST", "0.0.0.0")
	app_port: int = int(os.getenv("APP_PORT", "8000"))
	timezone: str = os.getenv("TIMEZONE", "Europe/Moscow")

	postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
	postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
	postgres_db: str = os.getenv("POSTGRES_DB", "ai_db")
	postgres_user: str = os.getenv("POSTGRES_USER", "ai_user")
	postgres_password: str = os.getenv("POSTGRES_PASSWORD", "ai_password")

	openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")

	telegram_bot_token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
	admin_chat_id: Optional[int] = int(os.getenv("ADMIN_CHAT_ID", "0")) or None

	smtp_host: Optional[str] = os.getenv("SMTP_HOST")
	smtp_port: Optional[int] = int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT") else None
	smtp_username: Optional[str] = os.getenv("SMTP_USERNAME")
	smtp_password: Optional[str] = os.getenv("SMTP_PASSWORD")
	smtp_from: Optional[str] = os.getenv("SMTP_FROM")
	smtp_to: Optional[str] = os.getenv("SMTP_TO")

	s3_endpoint_url: Optional[str] = os.getenv("S3_ENDPOINT_URL")
	s3_region: Optional[str] = os.getenv("S3_REGION")
	s3_access_key_id: Optional[str] = os.getenv("S3_ACCESS_KEY_ID")
	s3_secret_access_key: Optional[str] = os.getenv("S3_SECRET_ACCESS_KEY")
	s3_bucket: Optional[str] = os.getenv("S3_BUCKET")

	upload_dir: Optional[str] = os.getenv("UPLOAD_DIR", "uploads")
	web_base_url: Optional[str] = os.getenv("WEB_BASE_URL")

	# Admin credentials for basic-auth (dev: simple, prod: use secrets)
	admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
	admin_password: str = os.getenv("ADMIN_PASSWORD", "admin")

	@property
	def database_url(self) -> str:
		user = self.postgres_user
		password = self.postgres_password
		host = self.postgres_host
		port = self.postgres_port
		db = self.postgres_db
		return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


def get_settings() -> Settings:
	return Settings()