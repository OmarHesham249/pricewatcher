from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://sarak:sarak_secret_pass@postgres:5432/sarak_db"
    redis_url: str = "redis://redis:6379/0"
    default_user_email: str = "demo@sarak.eg"
    default_telegram_chat_id: str = "123456789"


settings = Settings()
