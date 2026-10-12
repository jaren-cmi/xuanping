from typing import Any

from xuanping.llm.client import LLMClient
from xuanping.llm.prompts import PAIN_POINTS_SYSTEM, PAIN_POINTS_USER
from xuanping.models import PainPoint


class PainPointAnalyzer:
    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm

    def analyze(self, reviews: list[str]) -> list[PainPoint]:
        if not reviews:
            return []
        llm = self.llm or LLMClient()
        result = llm.complete_json(
            [
                {"role": "system", "content": PAIN_POINTS_SYSTEM},
                {"role": "user", "content": PAIN_POINTS_USER.format(reviews="\n".join(reviews))},
            ]
        )
        return [PainPoint.model_validate(item) for item in result.get("pain_points", [])]
