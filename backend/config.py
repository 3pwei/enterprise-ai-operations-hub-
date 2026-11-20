import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = "sqlite:///./hub.db"
    demo_analyst_token: str = ""
    demo_manager_token: str = ""
    mcp_signing_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(**{key: os.getenv(key.upper(), field.default) for key, field in cls.model_fields.items()})


@lru_cache
def settings() -> Settings:
    return Settings.from_env()
