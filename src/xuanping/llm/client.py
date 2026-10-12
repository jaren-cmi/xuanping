import json
import logging
import re
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from xuanping.config import Settings, get_settings

logger = logging.getLogger(__name__)


def parse_json_response(content: str) -> Any:
    """解析纯 JSON 或被 Markdown 代码块包裹的 JSON。"""
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as original_error:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise original_error


class LLMClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if not self.settings.llm_api_key and client is None:
            raise ValueError("请在 .env 中配置所选 LLM provider 的 API Key")
        self.client = client or OpenAI(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.resolved_llm_base_url,
        )
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _request(self, messages: list[dict[str, str]], response_format: bool = True) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.settings.resolved_llm_model,
            "messages": messages,
        }
        if response_format:
            kwargs["response_format"] = {"type": "json_object"}
        return self.client.chat.completions.create(**kwargs)

    def complete_json(
        self, messages: list[dict[str, str]], *, response_format: bool = True
    ) -> Any:
        # 某些兼容接口不支持 response_format；失败后使用 prompt 约束并由解析器兜底。
        try:
            response = self._request(messages, response_format=response_format)
        except Exception as error:
            message = str(error).lower()
            if not response_format or not any(
                term in message for term in ("response_format", "json_object", "json mode")
            ):
                raise
            logger.debug("JSON 模式请求失败，退回普通聊天模式: %s", error)
            response = self._request_plain(messages)
        usage = getattr(response, "usage", None)
        if usage:
            self.total_prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.total_completion_tokens += getattr(usage, "completion_tokens", 0) or 0
        content = response.choices[0].message.content or ""
        return parse_json_response(content)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _request_plain(self, messages: list[dict[str, str]]) -> Any:
        return self.client.chat.completions.create(
            model=self.settings.resolved_llm_model,
            messages=messages,
        )
