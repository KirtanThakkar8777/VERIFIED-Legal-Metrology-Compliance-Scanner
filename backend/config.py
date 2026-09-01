from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "VERIFIED v2 — Legal Metrology Compliance Scanner"
    app_version: str = "2.0.0"
    database_url: str = "sqlite:///./data/verified.db"
    secret_key: str = "change-this-in-production-secret-key-min-32-chars"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours

    class Config:
        env_file = ".env"

settings = Settings()
