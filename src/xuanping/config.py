from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="XUANPING_", env_file=".env", env_file_encoding="utf-8",
        extra="ignore", populate_by_name=True,
    )

    llm_provider: str = "zhipu"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    amazon_domain: str = "www.amazon.com"
    request_delay_min: float = Field(default=2.0, ge=0)
    request_delay_max: float = Field(default=5.0, ge=0)
    proxies: str = ""
    proxy_strategy: str = "random"
    proxy_max_failures: int = Field(default=3, ge=1)
    proxy_cooldown: float = Field(default=300, ge=0)
    proxy_health_check: bool = False
    database_path: str = "xuanping.db"
    review_limit: int = Field(default=30, ge=0)
    default_cost_multiplier: float = Field(default=0.3, ge=0)
    enable_1688: bool = True
    cny_usd_rate: float = Field(default=7.2, gt=0)
    supplier_1688_candidates: int = Field(
        default=10, ge=1, validation_alias="XUANPING_1688_CANDIDATES"
    )
    trends_top_n: int = Field(default=20, ge=1)
    score_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "demand": 0.30,
            "competition": 0.20,
            "profit": 0.25,
            "opportunity": 0.15,
            "risk": 0.10,
        }
    )

    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"zhipu", "qwen"}:
            raise ValueError("llm_provider 必须为 zhipu 或 qwen")
        return value

    @model_validator(mode="after")
    def validate_delays(self) -> "Settings":
        if self.request_delay_max < self.request_delay_min:
            raise ValueError("request_delay_max 不能小于 request_delay_min")
        if set(self.score_weights) - {
            "demand",
            "competition",
            "profit",
            "opportunity",
            "risk",
        }:
            raise ValueError("score_weights 只能包含需求、竞争、利润、机会和风险维度")
        if self.proxy_strategy not in {"random", "round_robin"}:
            raise ValueError("proxy_strategy 必须为 random 或 round_robin")
        if any(weight < 0 for weight in self.score_weights.values()):
            raise ValueError("score_weights 权重不能为负数")
        if not any(weight > 0 for weight in self.score_weights.values()):
            raise ValueError("score_weights 至少需要一个正数")
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

    @property
    def proxy_pool(self) -> list[str]:
        return [proxy.strip() for proxy in self.proxies.split(",") if proxy.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
