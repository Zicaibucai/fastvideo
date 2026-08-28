"""AI 重新分镜流程。

正文守恒校验和镜头重排属于独立工作流，通过回调复用主引擎的模型解析、
节拍写入和文本身份规则，避免在大服务文件中继续堆叠状态转换。
"""

from __future__ import annotations

import json
from typing import Any

from app.adapters.factory import get_llm_adapter
from app.core.database import SessionLocal
from app.models.base import utc_now_iso
from app.models.storyboard_shot import StoryboardShot
from app.services.narration_schema import ResegmentShot, parse_resegment_output

def resegment_storyboard(params: dict[str, Any], *, complete_structured, create_narration_beats, resegment_identity, infer_source_sequences) -> dict[str, Any]:
    """根据现有正文重新划分镜头，严格禁止模型新增或删改事实文本。"""
    from app.services.ai_configuration import refresh_runtime_config_from_db

    refresh_runtime_config_from_db()
    project_id = params["project_id"]
    db = SessionLocal()
    try:
        shots = (
            db.query(StoryboardShot)
            .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
            .order_by(StoryboardShot.sequence.asc())
            .all()
        )
        if not shots:
            raise RuntimeError("当前没有可重新分镜的正文")
        adapter = get_llm_adapter()
        if not adapter.is_available():
            raise RuntimeError("LLM 服务不可用，请检查配置。")

        source = [
            {
                "sequence": shot.sequence,
                "title": shot.title or "",
                "section": shot.section or "",
                "narration": shot.narration or "",
                "durationSeconds": float(shot.duration_seconds or 1),
                "visualType": shot.visual_type or "generated_image",
                "visualDescription": shot.visual_description or "",
            }
            for shot in shots
        ]
        prompt = (
            "你是工程投标视频的分镜编辑。请只对现有解说词重新划分镜头，不要重写正文。\n"
            f"目标镜头数量：{int(params.get('target_shot_count', len(shots)))}\n"
            f"补充要求：{params.get('instructions') or '无'}\n\n"
            "硬性要求：\n"
            "1. 输出的 narration 必须逐字来自输入正文，只允许调整镜头边界和标点断句。\n"
            "2. 不得新增、删减、改写任何事实、数字、日期、型号、工序或结论。\n"
            "3. 每个输出镜头必须填写 sourceShotSequences，表示它由哪些原镜头组成。\n"
            "4. 可以合并或拆分镜头；标题、章节、画面描述可以重排，但不能写入正文没有的事实。\n"
            "5. 只输出合法 JSON，不要 Markdown 或解释。结构："
            '{"shots":[{"sequence":1,"title":"","section":"","narration":"",'
            '"durationSeconds":10,"visualType":"generated_image","visualDescription":"",'
            '"sourceShotSequences":[1]}]}\n\n'
            f"现有分镜：{json.dumps(source, ensure_ascii=False)}"
        )
        parsed = complete_structured(
            adapter,
            prompt,
            parse_resegment_output,
            stage="resegment",
            max_tokens=6000,
            temperature=0,
        )
        target_shots = parsed.shots[: int(params.get("target_shot_count", len(shots)))]
        if not target_shots:
            raise ValueError("AI 没有返回可用分镜")

        original_identity = resegment_identity("".join(shot.narration or "" for shot in shots))
        generated_identity = resegment_identity("".join(shot.narration or "" for shot in target_shots))
        if original_identity != generated_identity:
            raise ValueError("AI 重新分镜未完整保留原正文，本次调整未应用")

        old_by_sequence = {shot.sequence: shot for shot in shots}
        cursor = 0
        prepared: list[tuple[ResegmentShot, list[int]]] = []
        for item in target_shots:
            supplied = [seq for seq in item.sourceShotSequences if seq in old_by_sequence]
            inferred, cursor = infer_source_sequences(item.narration, shots, cursor)
            source_sequences = supplied or inferred
            if not source_sequences:
                raise ValueError(f"第{item.sequence}个新分镜缺少原镜头来源")
            prepared.append((item, list(dict.fromkeys(source_sequences))))

        total_duration = sum(float(shot.duration_seconds or 0) for shot in shots)
        if total_duration <= 0:
            total_duration = max(1.0, sum(len(shot.narration or "") for shot in shots) / max(1, int(params.get("chars_per_minute", 215))) * 60)
        weights = [max(1, len(resegment_identity(item.narration))) for item, _ in prepared]
        weight_total = sum(weights) or 1
        result_shots: list[StoryboardShot] = []
        used_existing_ids: set[str] = set()

        def merged_metadata(source_sequences: list[int]) -> tuple[list, list, str, str, str]:
            refs: list = []
            scoring: list = []
            statuses: list[str] = []
            for sequence in source_sequences:
                source_shot = old_by_sequence[sequence]
                for ref in source_shot.source_references or []:
                    if ref not in refs:
                        refs.append(ref)
                for score_id in source_shot.scoring_point_ids or []:
                    if score_id not in scoring:
                        scoring.append(score_id)
                if source_shot.fact_check_status:
                    statuses.append(source_shot.fact_check_status)
            if "conflict" in statuses:
                status = "conflict"
            elif statuses and all(value == "verified" for value in statuses):
                status = "verified"
            elif statuses:
                status = "partial"
            else:
                status = "unverified"
            first = old_by_sequence[source_sequences[0]]
            return refs, scoring, status, first.section or "", first.title or ""

        for index, (item, source_sequences) in enumerate(prepared, start=1):
            refs, scoring, status, fallback_section, fallback_title = merged_metadata(source_sequences)
            duration = max(1.0, total_duration * weights[index - 1] / weight_total)
            existing = next(
                (
                    old_by_sequence[sequence]
                    for sequence in source_sequences
                    if sequence in old_by_sequence and old_by_sequence[sequence].id not in used_existing_ids
                ),
                None,
            )
            if existing is None:
                existing = next((shot for shot in shots if shot.id not in used_existing_ids), None)
            title = item.title or fallback_title or f"第{index}段"
            section = item.section or fallback_section
            if existing:
                used_existing_ids.add(existing.id)
                old_narration = existing.narration or ""
                if old_narration != item.narration:
                    versions = list(existing.versions or [])
                    revision = max([v.get("revision", 0) for v in versions] + [0]) + 1
                    versions.append(
                        {
                            "revision": revision,
                            "narration": item.narration,
                            "visual_prompt": item.visualDescription or existing.visual_prompt,
                            "visual_type": item.visualType,
                            "created_at": utc_now_iso(),
                            "source": "ai_resegment",
                        }
                    )
                    existing.versions = versions
                    from app.services.voice_service import mark_shot_narration_changed

                    mark_shot_narration_changed(db, existing, old_narration, item.narration)
                existing.sequence = index
                existing.title = title
                existing.section = section
                existing.narration = item.narration
                existing.duration_seconds = duration
                existing.visual_type = item.visualType
                existing.visual_description = item.visualDescription
                existing.visual_prompt = item.visualDescription or existing.visual_prompt
                existing.source_references = refs
                existing.scoring_point_ids = scoring
                existing.fact_check_status = status
                existing.status = "edited"
                result_shots.append(existing)
            else:
                created = StoryboardShot(
                    project_id=project_id,
                    sequence=index,
                    title=title,
                    section=section,
                    narration=item.narration,
                    duration_seconds=duration,
                    visual_type=item.visualType,
                    visual_description=item.visualDescription,
                    visual_prompt=item.visualDescription,
                    source_references=refs,
                    scoring_point_ids=scoring,
                    fact_check_status=status,
                    status="ai_done",
                    versions=[
                        {
                            "revision": 1,
                            "narration": item.narration,
                            "visual_prompt": item.visualDescription,
                            "visual_type": item.visualType,
                            "created_at": utc_now_iso(),
                            "source": "ai_resegment",
                        }
                    ],
                )
                db.add(created)
                result_shots.append(created)

        for old_shot in shots:
            if old_shot.id not in used_existing_ids:
                db.delete(old_shot)
        db.flush()
        beat_count = create_narration_beats(db, project_id, result_shots, [], int(params.get("chars_per_minute", 215)))
        db.commit()
        return {
            "shot_count": len(result_shots),
            "beat_count": beat_count,
            "total_duration_seconds": round(sum(float(shot.duration_seconds or 0) for shot in result_shots), 1),
            "total_narration_characters": sum(len(shot.narration or "") for shot in result_shots),
            "status": "success",
        }
    finally:
        db.close()
