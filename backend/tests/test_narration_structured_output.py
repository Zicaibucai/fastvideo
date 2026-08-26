from __future__ import annotations

import json

from app.services.narration_engine import (
    EvidenceItem,
    SourceRef,
    _complete_structured,
    _extract_json,
    _format_evidence_for_outline,
    parse_chapter_draft_output,
    parse_outline_output,
)


def _outline_json() -> str:
    return json.dumps(
        {
            "totalDurationSeconds": 540,
            "targetCharacters": 1935,
            "chapters": [
                {
                    "sequence": 1,
                    "title": "施工总体部署",
                    "durationSeconds": 80,
                    "targetCharacters": 287,
                    "writingGoal": "说明施工组织主线",
                    "scoringFocus": [],
                    "visualPlan": "BIM总览",
                    "evidenceIndexes": [0],
                    "evidenceIds": [],
                }
            ],
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


def test_extract_json_accepts_prose_and_markdown_around_object():
    raw = f"下面是完整结果：\n```json\n{_outline_json()}\n```\n以上。"

    assert parse_outline_output(raw).chapters[0].title == "施工总体部署"


def test_structured_call_retries_with_larger_budget():
    adapter = _SequenceAdapter(["这次返回不完整", _outline_json()])

    result = _complete_structured(
        adapter,
        "请输出大纲 JSON",
        parse_outline_output,
        stage="outline",
        max_tokens=3500,
    )

    assert result.chapters[0].title == "施工总体部署"
    assert adapter.max_tokens == [3500, 7000]


def test_visual_type_aliases_are_normalised_before_schema_validation():
    raw = json.dumps(
        {
            "shots": [
                {
                    "sequence": 1,
                    "title": "施工总平面",
                    "section": "总体部署",
                    "narration": "展示施工总平面布置。",
                    "durationSeconds": 10,
                    "visualType": "map",
                }
            ],
            "unverifiedFacts": [],
        },
        ensure_ascii=False,
    )

    result = parse_chapter_draft_output(raw)

    assert result.shots[0].visualType == "infographic"


def test_outline_evidence_is_compact_and_topic_balanced():
    items = [
        EvidenceItem(
            topic=f"专题{index % 12}",
            fact=f"第{index}条工程事实，包含施工对象和控制关系",
            parameters=["10.1米", "120天"],
            constructionActions=["分层开挖", "验收"],
            sequenceContext="支护完成后进入下一道工序",
            sourceReference=SourceRef(documentName="招标文件", page=index + 1, quote="原文依据"),
        )
        for index in range(240)
    ]

    text = _format_evidence_for_outline(items)

    assert len(text) < 50000
    for index in range(12):
        assert f"专题{index}" in text
    assert "[0]" in text
