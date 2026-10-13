import json

import pytest

from xuanping.analysis.pain_points import PainPointAnalyzer
from xuanping.analysis.sourcing import SourcingAnalyzer
from xuanping.models import Product


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.messages = []

    def complete_json(self, messages):
        self.messages.append(messages)
        return self.response


@pytest.mark.parametrize(
    ("scores", "prices", "confidence"),
    [
        ([85], [(36, 40)], "medium"),
        ([84], [(36, 40)], "low"),
        ([90, 86], [(36, 40), (38, 42)], "high"),
        ([70, 65], [(36, 40), (38, 42)], "medium"),
        ([90, 86], [(10, 12), (100, 120)], "low"),
        ([90, 86], [(1, 100), (1, 100)], "low"),
        ([90, 60], [(36, 40), (38, 42)], "low"),
        ([90, 86, 80], [(36, 40), (38, 42), (37, 41)], "high"),
        ([], [], "low"),
        ([90], [(None, None)], "low"),
        ([90], [(-1, 10)], "low"),
    ],
)
def test_sourcing_confidence(scores, prices, confidence):
    llm = FakeLLM({"matches": [
        {"index": index, "score": score} for index, score in enumerate(scores)
    ]})
    result = SourcingAnalyzer(llm).match(
        Product(asin="test"),
        [{"title": "杯子", "price_min_cny": low, "price_max_cny": high} for low, high in prices],
    )
    assert result["confidence"] == confidence
    if len(prices) <= 1:
        assert result["spread"] is None
    if not prices or prices[0][0] is None or prices[0][0] < 0:
        assert result["cost_min_usd"] is None
    if not prices:
        assert llm.messages == []


def test_sourcing_user_messages_are_valid_json_with_special_characters():
    title = '中文 "cup" \\ portable\nnew line'
    llm = FakeLLM({"keywords": "杯子", "matches": [{"index": 0, "score": 90}]})
    sourcing = SourcingAnalyzer(llm)
    sourcing.search_terms(title)
    sourcing.match(
        Product(asin="test", title=title, bullets=[title]),
        [{"title": title}, {"title": None}],
    )
    search = json.loads(llm.messages[0][1]["content"])
    matching = json.loads(llm.messages[1][1]["content"])
    assert search == {"title": title}
    assert matching["amazon"] == {"title": title, "bullets": [title]}
    assert matching["offers"] == [{"title": title, "index": 0}, {"title": None, "index": 1}]
    assert "中文" in llm.messages[0][1]["content"]


def test_pain_point_user_message_preserves_review_boundaries_as_json():
    reviews = ['中文 "quote" \\ slash\nnewline', "second review"]
    llm = FakeLLM({"pain_points": []})
    assert PainPointAnalyzer(llm).analyze(reviews) == []
    assert json.loads(llm.messages[0][1]["content"]) == {"reviews": reviews}
    assert "中文" in llm.messages[0][1]["content"]
