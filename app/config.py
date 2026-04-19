from typing import Optional
from pydantic_settings import BaseSettings
from tortoise import Tortoise
from app.utils.auto_routing import get_single_app_structure


class Settings(BaseSettings):
    DEBUG: bool = True
    APP_NAME: str = "Kujunbrown App"

    EMAIL_HOST: str = "smtp.gmail.com"
    EMAIL_PORT: int = 587
    EMAIL_HOST_USER: str = "lookuparchitecture@gmail.com"
    EMAIL_HOST_PASSWORD: str = "ihuciytlvdymggol"
    DEFAULT_FROM_EMAIL: str = "lookuparchitecture@gmail.com"

    MEDIA_DIR: str = "media/"
    MEDIA_ROOT: str = "media/"
    ENV: str = "development"
    DB_HOST: str = "localhost"
    DB_NAME: str = "db.sqlite3"
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_ROOT_PASSWORD: str = ""
    DB_PORT: int = 5432
    DB_ENGINE: str = "postgres"

    DATABASE_URL: Optional[str] = None
    SECRET_KEY: Optional[str] = None
    BASE_URL: str = "http://localhost:8000/"
    REDIS_URL: str = "redis://redis:6379/0"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # 7 days
    REFRESH_TOKEN_EXPIRE_DAYS: int = 60

    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""

    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    FIREBASE_KEY_BASE64: str = ""

    def model_post_init(self, __context):
        if self.DB_ENGINE == "sqlite":
            self.DATABASE_URL = f"sqlite:///{self.DB_NAME}"
        else:
            self.DATABASE_URL = (
                f"{self.DB_ENGINE}://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

apps_config = get_single_app_structure("applications")
import json

print(json.dumps(apps_config, indent=4))

TORTOISE_ORM = {
    "connections": {
        "default": settings.DATABASE_URL,
    },
    "apps": get_single_app_structure("applications"),
    "use_tz": True,
    "timezone": "Asia/Dhaka",
}


async def init_db():
    await Tortoise.init(config=TORTOISE_ORM)
    if settings.ENV != "production":
        await Tortoise.generate_schemas()
    else:
        print("Skipping schema generation in production.")
