"""超长文档证据提取容错测试。"""

from __future__ import annotations

import json

import pytest

from app.services.narration_evidence import _complete_evidence_batch


def _valid_output() -> str:
    return json.dumps(
        {
            "evidenceItems": [
                {
                    "topic": "基坑土方",
                    "fact": "土方分层开挖",
                    "parameters": ["10.1米"],
                    "constructionActions": ["分层开挖"],
                    "sequenceContext": "支护完成后开挖",
                    "sourceChunkIds": ["chunk-1"],
                    "sourceReference": {"locationLabel": "块1", "quote": "土方分层开挖"},
                    "factCheckStatus": "verified",
                }
            ],
            "rejectedFacts": [],
        },
        ensure_ascii=False,
    )


class _SequenceAdapter:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.max_tokens: list[int] = []

    def complete(self, _prompt: str, **kwargs) -> str:
        self.max_tokens.append(kwargs["max_tokens"])
        return self.responses.pop(0)


def test_truncated_evidence_json_retries_with_larger_budget():
    adapter = _SequenceAdapter(['{"evidenceItems":[{"fact":"未闭合', _valid_output()])

    result = _complete_evidence_batch(adapter, "证据提取提示")

    assert result.evidenceItems[0].fact == "土方分层开挖"
    assert adapter.max_tokens == [12000, 20000]


def test_valid_evidence_json_does_not_retry():
    adapter = _SequenceAdapter([_valid_output()])

    result = _complete_evidence_batch(adapter, "证据提取提示")

    assert len(result.evidenceItems) == 1
    assert adapter.max_tokens == [12000]


def test_nullable_optional_evidence_fields_are_normalised():
    payload = json.loads(_valid_output())
    payload["evidenceItems"][0].update(
        {
            "parameters": None,
            "constructionActions": None,
            "sequenceContext": None,
            "sourceChunkIds": ["chunk-1", None],
            "sourceReference": None,
            "factCheckStatus": None,
        }
    )
    adapter = _SequenceAdapter([json.dumps(payload, ensure_ascii=False)])

    result = _complete_evidence_batch(adapter, "证据提取提示")

    item = result.evidenceItems[0]
    assert item.sequenceContext == ""
    assert item.parameters == []
    assert item.constructionActions == []
    assert item.sourceChunkIds == ["chunk-1"]
    assert item.sourceReference == {}
    assert item.factCheckStatus == "partial"
    assert adapter.max_tokens == [12000]


def test_repeated_invalid_evidence_json_reports_clear_error():
    adapter = _SequenceAdapter(["{", '{"evidenceItems":['])

    with pytest.raises(ValueError, match="连续返回无法使用的结构"):
        _complete_evidence_batch(adapter, "证据提取提示")

    assert adapter.max_tokens == [12000, 20000]
