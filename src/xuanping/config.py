from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="XUANPING_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    llm_provider: str = "zhipu"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    amazon_domain: str = "www.amazon.com"
    request_delay_min: float = Field(default=2.0, ge=0)
    request_delay_max: float = Field(default=5.0, ge=0)
    proxies: list[str] = Field(default_factory=list)
    database_path: str = "xuanping.db"
    review_limit: int = Field(default=30, ge=0)
    default_cost_multiplier: float = Field(default=0.3, ge=0)

    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"zhipu", "qwen"}:
            raise ValueError("llm_provider 必须为 zhipu 或 qwen")
        return value

    @field_validator("proxies", mode="before")
    @classmethod
    def split_proxies(cls, value: object) -> object:
        if isinstance(value, str):
            return [proxy.strip() for proxy in value.split(",") if proxy.strip()]
        return value

    @model_validator(mode="after")
    def validate_delays(self) -> "Settings":
        if self.request_delay_max < self.request_delay_min:
            raise ValueError("request_delay_max 不能小于 request_delay_min")
        return self

    @property
    def resolved_llm_base_url(self) -> str:
        if self.llm_base_url:
            return self.llm_base_url.rstrip("/") + "/"
        if self.llm_provider == "qwen":
            return "https://dashscope.aliyuncs.com/compatible-mode/v1"
        return "https://open.bigmodel.cn/api/paas/v4/"

    @property
    def resolved_llm_model(self) -> str:
        if self.llm_model:
            return self.llm_model
        return "qwen-plus" if self.llm_provider == "qwen" else "glm-4-flash"


@lru_cache
def get_settings() -> Settings:
    return Settings()
