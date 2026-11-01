from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/event_registration"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "noreply@events.local"
    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 20
    scheduler_poll_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
