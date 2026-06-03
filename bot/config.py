from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    group_chat_id: int = Field(alias="GROUP_CHAT_ID")
    admin_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list,
        alias="ADMIN_IDS",
    )
    seller_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list,
        alias="SELLER_IDS",
    )
    allowed_user_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list,
        alias="ALLOWED_USER_IDS",
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/bot.db",
        alias="DATABASE_URL",
    )
    default_currency: str = Field(default="RUB", alias="DEFAULT_CURRENCY")
    auction_timezone: str = Field(default="Europe/Chisinau", alias="AUCTION_TIMEZONE")

    @field_validator("admin_ids", "seller_ids", "allowed_user_ids", mode="before")
    @classmethod
    def parse_id_list(cls, value: Any) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [int(x) for x in value]
        return [int(x.strip()) for x in str(value).split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
