import pytest

from xuanping.llm.client import parse_json_response


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ('{"answer": 42}', {"answer": 42}),
        ('```json\n{"answer": 42}\n```', {"answer": 42}),
        ('Here is the result: {"answer": 42}', {"answer": 42}),
    ],
)
def test_parse_json_response_tolerates_wrappers(response, expected):
    assert parse_json_response(response) == expected


def test_parse_json_response_rejects_invalid_content():
    with pytest.raises(ValueError):
        parse_json_response("not JSON")
