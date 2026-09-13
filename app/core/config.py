from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://rag:rag@localhost:5432/rag"
    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    chunk_size: int = 900
    chunk_overlap: int = 150
    query_cache_ttl: int = 300
    top_k_default: int = 5

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
