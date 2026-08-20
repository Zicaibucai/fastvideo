"""视频工程编排服务（Phase 5）。

职责：
- 分镜 ↔ 分段同步（sync-storyboard）
- 素材选择（手动 > 绑定视频 > AI图 > 模型截图 > 占位卡）
- 分段时长计算、input_hash 缓存
- 单分镜渲染、全片合成、字幕/音乐/转场/Logo/片头片尾
- 导出前检查（demo/formal 严格区分）、导出报告
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import storage
from app.models.asset import Asset
from app.models.audio_version import AudioVersion
from app.models.export_task import ExportTask
from app.models.extracted_fact import ExtractedFact
from app.models.render_task import RenderTask
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.models.video_project import VideoProject
from app.models.video_segment import VideoSegment
from app.models.voice_template import VoiceTemplate
from app.services.audio_utils import render_srt
from app.services.video_composer import (
    build_ass,
    build_music_track,
    compute_input_hash,
    concat_audio,
    concat_with_transitions,
    duck_and_mix,
    make_silence_wav,
    mux,
    overlay_logo,
    probe_media,
    render_image_segment,
    render_title_card,
    render_video_segment,
)

logger = get_logger(__name__)

PAUSE_LEAD = 0.4  # 片头停顿
PAUSE_TAIL = 0.4  # 片尾停顿
MIN_SEGMENT_DURATION = 1.5
MAX_SEGMENT_DURATION = 60.0

FORMAL_FORBIDDEN_AUTH = {"unknown", "pending", "rejected", "expired", "mock_only"}


class VideoProjectError(Exception):
    def __init__(self, message: str, issues: list[dict] | None = None) -> None:
        self.message = message
        self.issues = issues or []
        super().__init__(message)


# ============================================================
# 同步分镜 → 分段
# ============================================================

def sync_storyboard_to_video_project(db: Session, vp: VideoProject, user: User | None = None) -> dict:
    """把项目分镜同步为视频分段（新增缺失分段，标记被删除分镜）。"""
    shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == vp.project_id)
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    existing = {s.storyboard_shot_id: s for s in db.query(VideoSegment).filter(VideoSegment.video_project_id == vp.id).all()}

    created = 0
    updated = 0
    for shot in shots:
        seg = existing.get(shot.id)
        if not seg:
            seg = VideoSegment(
                video_project_id=vp.id,
                storyboard_shot_id=shot.id,
                sequence=shot.sequence,
                duration=_default_duration(db, shot),
                render_status="pending",
                needs_rebuild=True,
            )
            db.add(seg)
            created += 1
        else:
            if seg.sequence != shot.sequence:
                seg.sequence = shot.sequence
                updated += 1
    # 已被删除的分镜 → 标记跳过
    valid_ids = {s.id for s in shots}
    for seg in existing.values():
        if seg.storyboard_shot_id and seg.storyboard_shot_id not in valid_ids:
            seg.render_status = "skipped"
            seg.needs_rebuild = True
    db.commit()
    for seg in db.query(VideoSegment).filter(VideoSegment.video_project_id == vp.id).all():
        _auto_select_assets(db, seg)
    db.commit()
    return {"created": created, "updated": updated, "segment_count": db.query(VideoSegment).filter(VideoSegment.video_project_id == vp.id).count()}


def _default_duration(db: Session, shot: StoryboardShot) -> float:
    audio = _selected_audio(db, shot)
    if audio and audio.actual_duration_seconds:
        return _clamp_duration(audio.actual_duration_seconds + PAUSE_LEAD + PAUSE_TAIL)
    if shot.duration_seconds:
        return _clamp_duration(shot.duration_seconds)
    return 5.0


def _clamp_duration(d: float) -> float:
    return round(max(MIN_SEGMENT_DURATION, min(MAX_SEGMENT_DURATION, d)), 3)


def _selected_audio(db: Session, shot: StoryboardShot) -> AudioVersion | None:
    return (
        db.query(AudioVersion)
        .filter(
            AudioVersion.storyboard_shot_id == shot.id,
            AudioVersion.project_id == shot.project_id,
            AudioVersion.is_selected.is_(True),
            AudioVersion.is_deleted.is_(False),
            AudioVersion.is_stale.is_(False),
        )
        .first()
    )


def _auto_select_assets(db: Session, seg: VideoSegment) -> None:
    """自动选择画面与配音（不覆盖手动指定）。"""
    if not seg.storyboard_shot_id:
        return
    shot = db.get(StoryboardShot, seg.storyboard_shot_id)
    if not shot:
        return
    if not seg.visual_asset_id:
        seg.visual_asset_id = shot.video_asset_id or shot.image_asset_id or shot.source_model_asset_id
    if not seg.audio_version_id:
        audio = _selected_audio(db, shot)
        if audio:
            seg.audio_version_id = audio.id


# ============================================================
# 素材解析
# ============================================================

def resolve_visual(db: Session, vp: VideoProject, seg: VideoSegment) -> tuple[bytes | None, str]:
    """按优先级解析画面素材：手动 > 绑定视频 > AI图 > 模型截图 > 占位卡。"""
    asset_id = seg.visual_asset_id
    asset = db.get(Asset, asset_id) if asset_id else None
    if asset and asset.file_key:
        data = storage.load(asset.file_key)
        if data:
            kind = "video" if asset.asset_type == "video" else "image"
            return data, kind
    if not asset and seg.storyboard_shot_id:
        shot = db.get(StoryboardShot, seg.storyboard_shot_id)
        if shot:
            for aid in (shot.video_asset_id, shot.image_asset_id, shot.source_model_asset_id):
                if aid:
                    a = db.get(Asset, aid)
                    if a and a.file_key:
                        data = storage.load(a.file_key)
                        if data:
                            kind = "video" if a.asset_type == "video" else "image"
                            return data, kind
    return None, "placeholder"


def resolve_audio(db: Session, vp: VideoProject, seg: VideoSegment) -> tuple[bytes | None, AudioVersion | None]:
    """解析配音：手动指定版本 > 分镜正式版本 > shot.audio_asset_id > None(静音)。"""
    if seg.audio_version_id:
        ver = db.get(AudioVersion, seg.audio_version_id)
        if ver and not ver.is_deleted:
            asset = db.get(Asset, ver.mp3_asset_id or ver.audio_asset_id) if (ver.mp3_asset_id or ver.audio_asset_id) else None
            if asset and asset.file_key:
                return storage.load(asset.file_key), ver
    if seg.storyboard_shot_id:
        shot = db.get(StoryboardShot, seg.storyboard_shot_id)
        if shot:
            ver = _selected_audio(db, shot)
            if ver:
                asset = db.get(Asset, ver.mp3_asset_id or ver.audio_asset_id) if (ver.mp3_asset_id or ver.audio_asset_id) else None
                if asset and asset.file_key:
                    return storage.load(asset.file_key), ver
            if shot.audio_asset_id:
                asset = db.get(Asset, shot.audio_asset_id)
                if asset and asset.file_key:
                    return storage.load(asset.file_key), None
    return None, None


def resolve_subtitles(db: Session, seg: VideoSegment) -> list[dict]:
    if not seg.subtitle_enabled:
        return []
    if seg.audio_version_id:
        ver = db.get(AudioVersion, seg.audio_version_id)
        if ver and ver.subtitle_data:
            return ver.subtitle_data
    if seg.storyboard_shot_id:
        shot = db.get(StoryboardShot, seg.storyboard_shot_id)
        if shot:
            ver = _selected_audio(db, shot)
            if ver and ver.subtitle_data:
                return ver.subtitle_data
    return []


# ============================================================
# input_hash
# ============================================================

def compute_segment_input_hash(db: Session, vp: VideoProject, seg: VideoSegment) -> str:
    """计算分段输入哈希：画面/配音/字幕/时长/运动/转场/分辨率/fps/字幕样式/Logo。"""
    visual_id = seg.visual_asset_id
    visual_sha = None
    if visual_id:
        a = db.get(Asset, visual_id)
        visual_sha = a.sha256 if a else None
    audio_sha = None
    if seg.audio_version_id:
        ver = db.get(AudioVersion, seg.audio_version_id)
        if ver:
            asset = db.get(Asset, ver.mp3_asset_id or ver.audio_asset_id) if (ver.mp3_asset_id or ver.audio_asset_id) else None
            audio_sha = asset.sha256 if asset else ver.narration_hash
    subs = resolve_subtitles(db, seg)
    return compute_input_hash(
        visual_asset_id=visual_id,
        visual_sha256=visual_sha,
        audio_version_id=seg.audio_version_id,
        audio_sha256=audio_sha,
        subtitle_text=json.dumps(subs, ensure_ascii=False),
        duration=seg.duration,
        motion=seg.visual_motion,
        fit_mode=seg.fit_mode,
        transition_type=seg.transition_type,
        transition_duration=seg.transition_duration,
        subtitle_enabled=seg.subtitle_enabled,
        subtitle_style=vp.subtitle_style,
        width=vp.width,
        height=vp.height,
        fps=vp.fps,
        logo=vp.logo_config,
    )


def mark_segments_needs_rebuild(db: Session, project_id: str, shot_id: str, reason: str) -> list[str]:
    """分镜画面/配音/解说词变化时，标记相关分段重建。"""
    affected = []
    vps = db.query(VideoProject).filter(VideoProject.project_id == project_id).all()
    for vp in vps:
        segs = db.query(VideoSegment).filter(VideoSegment.video_project_id == vp.id, VideoSegment.storyboard_shot_id == shot_id).all()
        for seg in segs:
            seg.needs_rebuild = True
            seg.render_status = "pending"
            affected.append(seg.id)
    if affected:
        db.commit()
    return affected


# ============================================================
# 单分镜渲染
# ============================================================

def render_segment(db: Session, segment_id: str) -> dict[str, Any]:
    """渲染单个分段为标准化 segment.mp4。"""
    seg = db.get(VideoSegment, segment_id)
    if not seg:
        raise VideoProjectError("分段不存在")
    vp = db.get(VideoProject, seg.video_project_id)
    if not vp:
        raise VideoProjectError("视频工程不存在")
    if seg.render_status == "cancelled":
        return {"status": "cancelled", "segment_id": segment_id}

    seg.render_status = "running"
    seg.render_progress = 10
    db.commit()

    duration = _clamp_duration(seg.duration)
    w, h, fps = vp.width or 1920, vp.height or 1080, vp.fps or 25
    audio_bytes, ver = resolve_audio(db, vp, seg)
    subs = resolve_subtitles(db, seg)

    with __import__("tempfile").TemporaryDirectory(prefix="fv_seg_") as td:
        from pathlib import Path

        tmp = Path(td)
        ass_path = None
        if subs:
            ass = build_ass(subs, style=vp.subtitle_style, width=w, height=h)
            ass_file = tmp / "sub.ass"
            ass_file.write_text(ass, encoding="utf-8")
            ass_path = str(ass_file)

        visual_bytes, kind = resolve_visual(db, vp, seg)
        try:
            if kind == "image":
                data = render_image_segment(
                    visual_bytes, duration=duration, motion=seg.visual_motion,
                    fit_mode=seg.fit_mode, width=w, height=h, fps=fps,
                    audio_bytes=audio_bytes, volume=seg.volume, ass_path=ass_path,
                )
            elif kind == "video":
                data = render_video_segment(
                    visual_bytes, duration=duration, fit_mode=seg.fit_mode,
                    motion=seg.visual_motion, width=w, height=h, fps=fps,
                    audio_bytes=audio_bytes, volume=seg.volume, short_video="loop",
                )
            else:
                shot = db.get(StoryboardShot, seg.storyboard_shot_id) if seg.storyboard_shot_id else None
                title = f"演示占位·{shot.title if shot and shot.title else '分镜'}"
                data = render_title_card(
                    title, "演示版（占位画面）", duration=duration,
                    width=w, height=h, fps=fps, brand_color=vp.brand_color,
                    audio_bytes=audio_bytes,
                )
        except Exception as exc:
            logger.exception("segment_render_failed", segment_id=segment_id)
            seg.render_status = "failed"
            seg.error_message = str(exc)[:2000]
            seg.render_progress = 0
            db.commit()
            raise VideoProjectError(f"分段渲染失败: {exc}")

        seg.render_progress = 80
        db.commit()

        key = f"projects/{vp.project_id}/video_projects/{vp.id}/segments/{seg.id}.mp4"
        storage.save(key, data)
        seg.output_key = key
        seg.render_status = "success"
        seg.render_progress = 100
        seg.input_hash = compute_segment_input_hash(db, vp, seg)
        seg.needs_rebuild = False
        seg.error_message = None
        seg.rendered_at = time.strftime("%Y-%m-%d %H:%M:%S")
        db.commit()

    return {"status": "success", "segment_id": segment_id, "output_key": key}


# ============================================================
# 导出前检查
# ============================================================

def _is_mock_asset(db: Session, asset_id: str | None) -> bool:
    if not asset_id:
        return False
    asset = db.get(Asset, asset_id)
    if not asset:
        return False
    if asset.meta and asset.meta.get("is_mock"):
        return True
    if asset.generated_by == "mock":
        return True
    if asset.ai_disclaimer and "Mock" in (asset.ai_disclaimer or ""):
        return True
    return False


def preflight(db: Session, vp: VideoProject, mode: str = "demo") -> dict[str, Any]:
    """导出前检查。mode: demo | formal。"""
    issues: list[dict] = []
    segs = (
        db.query(VideoSegment)
        .filter(VideoSegment.video_project_id == vp.id, VideoSegment.render_status != "skipped")
        .order_by(VideoSegment.sequence.asc())
        .all()
    )
    mock_mode = not settings.ai_keys_configured
    rendered = 0

    for seg in segs:
        shot = db.get(StoryboardShot, seg.storyboard_shot_id) if seg.storyboard_shot_id else None
        visual_bytes, kind = resolve_visual(db, vp, seg)
        if kind == "placeholder":
            issues.append({
                "level": "error" if mode == "formal" else "warning",
                "code": "missing_visual",
                "message": f"分镜「{shot.title if shot else '?'}」缺少画面素材（将使用占位卡）",
            })
        elif mode == "formal":
            effective_visual_id = seg.visual_asset_id
            if not effective_visual_id and shot:
                effective_visual_id = (
                    shot.video_asset_id or shot.image_asset_id or shot.source_model_asset_id
                )
            if _is_mock_asset(db, effective_visual_id):
                issues.append({"level": "error", "code": "mock_visual", "message": f"分镜「{shot.title if shot else '?'}」使用 Mock 画面，正式导出禁止。"})

        audio_bytes, ver = resolve_audio(db, vp, seg)
        if not audio_bytes:
            issues.append({"level": "warning", "code": "no_audio", "message": f"分镜「{shot.title if shot else '?'}」无配音，将使用静音轨。"})
        else:
            if mode == "formal":
                if ver and ver.is_mock:
                    issues.append({"level": "error", "code": "mock_audio", "message": f"分镜「{shot.title if shot else '?'}」使用 Mock 配音，正式导出禁止。"})
                if not ver and shot and _is_mock_asset(db, shot.audio_asset_id):
                    issues.append({"level": "error", "code": "mock_audio", "message": f"分镜「{shot.title if shot else '?'}」使用 Mock 配音，正式导出禁止。"})
                if ver and ver.is_stale:
                    issues.append({"level": "error", "code": "stale_audio", "message": f"分镜「{shot.title if shot else '?'}」配音已过期（解说词已修改）。"})
                auth = (ver.authorization_snapshot or {}).get("authorization_status") if ver else None
                if auth in FORMAL_FORBIDDEN_AUTH:
                    issues.append({"level": "error", "code": "unauthorized_voice", "message": f"分镜「{shot.title if shot else '?'}」音色授权状态为 {auth}，正式导出禁止。"})
        if seg.render_status == "success" and seg.output_key:
            rendered += 1
        elif seg.render_status == "failed":
            issues.append({"level": "error", "code": "render_failed", "message": f"分段「{shot.title if shot else '?'}」渲染失败：{seg.error_message}"})

    # 背景音乐授权
    for mt in (vp.music_tracks or []):
        auth = mt.get("authorization_status", "approved")
        if mode == "formal" and auth in FORMAL_FORBIDDEN_AUTH:
            issues.append({"level": "error", "code": "music_unauthorized", "message": f"背景音乐「{mt.get('name', '?')}」授权状态异常（{auth}），正式导出禁止。"})
        elif not mt.get("authorization_note") and not mt.get("authorization_status") == "approved":
            issues.append({"level": "warning", "code": "music_license", "message": f"背景音乐「{mt.get('name', '?')}」未填写版权信息。"})

    # 未确认/冲突工程数据
    facts = (
        db.query(ExtractedFact)
        .filter(
            ExtractedFact.project_id == vp.project_id,
            ExtractedFact.verification_status.in_(["unverified", "conflict"]),
        )
        .all()
    )
    if facts and mode == "formal":
        issues.append({"level": "error", "code": "unverified_facts", "message": f"存在 {len(facts)} 条未确认或冲突的工程参数，正式导出前请先确认。"})
    elif facts:
        issues.append({"level": "warning", "code": "unverified_facts", "message": f"存在 {len(facts)} 条未确认或冲突的工程参数。"})

    # Logo
    if vp.logo_config and vp.logo_config.get("asset_id"):
        logo = db.get(Asset, vp.logo_config["asset_id"])
        if not logo:
            issues.append({"level": "warning", "code": "logo_missing", "message": "Logo 素材不存在，导出将不叠加 Logo。"})

    # 总时长
    total = sum(s.duration for s in segs)
    if vp.duration_seconds and vp.duration_seconds > 0:
        ratio = abs(total - vp.duration_seconds) / vp.duration_seconds
        if ratio > 0.2:
            issues.append({"level": "warning", "code": "duration_mismatch", "message": f"分段总时长 {total:.1f}s 与目标 {vp.duration_seconds}s 偏差较大。"})

    errors = [i for i in issues if i["level"] == "error"]
    return {
        "ok": not errors,
        "mode": mode,
        "issues": issues,
        "segment_count": len(segs),
        "rendered_segment_count": rendered,
        "missing_render_count": len(segs) - rendered,
        "mock_mode": mock_mode,
    }


# ============================================================
# 全片合成
# ============================================================

def compose_project(db: Session, export_task_id: str) -> dict[str, Any]:
    """全片合成：分段 → 转场拼接 → 音乐混音 → Logo → mux → 字幕/报告。"""
    export_task = db.get(ExportTask, export_task_id)
    if not export_task:
        raise VideoProjectError("导出任务不存在")
    vp = db.get(VideoProject, export_task.video_project_id)
    if not vp:
        raise VideoProjectError("视频工程不存在")
    mode = export_task.mode

    check = preflight(db, vp, mode)
    if mode == "formal" and not check["ok"]:
        raise VideoProjectError("正式导出前检查未通过", check["issues"])

    segs = (
        db.query(VideoSegment)
        .filter(VideoSegment.video_project_id == vp.id, VideoSegment.render_status == "success")
        .order_by(VideoSegment.sequence.asc())
        .all()
    )
    if not segs:
        raise VideoProjectError("没有可合成的分段，请先生成分段。")

    w, h, fps = vp.width or 1920, vp.height or 1080, vp.fps or 25
    export_task.progress = 30
    export_task.status = "running"
    db.commit()

    # 1) 加载各分段并分离音视频
    video_items: list[dict] = []
    audio_items: list[dict] = []
    total_duration = 0.0

    with __import__("tempfile").TemporaryDirectory(prefix="fv_compose_") as td:
        from pathlib import Path

        tmp = Path(td)
        # 片头
        open_item = _build_open_card(db, vp, w, h, fps, tmp)
        items: list[dict] = []
        if open_item:
            items.append(open_item)
        for seg in segs:
            items.append(_load_segment_item(db, seg, tmp))
        close_item = _build_close_card(db, vp, w, h, fps, tmp)
        if close_item:
            items.append(close_item)

        for it in items:
            total_duration += float(it["duration"])
            video_items.append(it)
            audio_items.append({
                "path": it["audio_path"],
                "duration": it["duration"],
                "transition_type": it["transition_type"],
                "transition_duration": it["transition_duration"],
            })

        # 2) 视频转场拼接
        export_task.progress = 45
        db.commit()
        final_video, final_total = concat_with_transitions(video_items, width=w, height=h, fps=fps)

        # 3) 音频拼接（acrossfade）
        dub_audio = concat_audio(audio_items, final_total)

        # 4) 背景音乐
        music_bytes = None
        if vp.music_tracks:
            music_files = []
            for mt in vp.music_tracks:
                asset = db.get(Asset, mt.get("asset_id")) if mt.get("asset_id") else None
                if asset and asset.file_key:
                    mp = tmp / f"music_{asset.id}.m4a"
                    _write_bytes(mp, storage.load(asset.file_key))
                    music_files.append({
                        "path": str(mp),
                        "volume": float(mt.get("volume", 0.7)),
                        "fade_in": float(mt.get("fade_in", 1.0)),
                        "fade_out": float(mt.get("fade_out", 2.0)),
                    })
            if music_files:
                music_bytes = build_music_track(music_files, total_duration=final_total)

        # 5) 混音（配音优先 + ducking）
        mixed = duck_and_mix(dub_audio, music_bytes, ducking=True)

        # 6) Logo 叠加
        if vp.logo_config and vp.logo_config.get("asset_id"):
            logo_asset = db.get(Asset, vp.logo_config["asset_id"])
            if logo_asset and logo_asset.file_key:
                logo_bytes = storage.load(logo_asset.file_key)
                try:
                    final_video = overlay_logo(
                        final_video, logo_bytes,
                        position=vp.logo_config.get("position", "top_right"),
                        size_ratio=float(vp.logo_config.get("size", 0.12)),
                        opacity=float(vp.logo_config.get("opacity", 0.9)),
                    )
                except Exception as exc:
                    logger.warning("logo_overlay_failed", error=str(exc))

        # 7) mux
        export_task.progress = 75
        db.commit()
        final_mp4 = mux(final_video, mixed, fps=fps)

        # 8) 生成 SRT 与报告
        export_task.progress = 85
        db.commit()
        srt_content = _project_srt(db, vp, items, segs)
        report = build_export_report(db, vp, mode, check, items, final_total)

        # 保存
        out_key = f"projects/{vp.project_id}/video_projects/{vp.id}/final_{mode}_{time.strftime('%Y%m%d%H%M%S')}.mp4"
        storage.save(out_key, final_mp4)
        srt_key = out_key.replace(".mp4", ".srt")
        storage.save(srt_key, srt_content.encode("utf-8"))
        report_key = out_key.replace(".mp4", "_report.json")
        storage.save(report_key, json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))

        vp.status = "success"
        vp.output_key = out_key
        vp.output_url = storage.url(out_key)
        vp.duration_seconds = final_total
        vp.timeline_snapshot = _timeline_snapshot(vp, items, segs)

        export_task.status = "success"
        export_task.progress = 100
        export_task.output_key = out_key
        export_task.output_url = storage.url(out_key)
        export_task.srt_key = srt_key
        export_task.report_key = report_key
        export_task.duration_seconds = final_total
        export_task.timeline_snapshot = vp.timeline_snapshot
        db.commit()

        info = probe_media(final_mp4, suffix=".mp4")
        return {
            "output_key": out_key,
            "duration": final_total,
            "width": info.get("width"),
            "height": info.get("height"),
            "fps": info.get("fps"),
            "vcodec": info.get("vcodec"),
            "acodec": info.get("acodec"),
            "srt_key": srt_key,
            "report_key": report_key,
        }


def _load_segment_item(db: Session, seg: VideoSegment, tmp: Path) -> dict:
    data = storage.load(seg.output_key)
    video_path = tmp / f"seg_{seg.id}.mp4"
    _write_bytes(video_path, data)
    audio_path = tmp / f"seg_{seg.id}.m4a"
    _extract_audio(video_path, audio_path)
    return {
        "path": str(video_path),
        "audio_path": str(audio_path),
        "duration": seg.duration,
        "transition_type": seg.transition_type,
        "transition_duration": seg.transition_duration,
        "shot_id": seg.storyboard_shot_id,
    }


def _extract_audio(video_path: Path, audio_path: Path) -> None:
    import subprocess

    subprocess.run(
        [settings.ffmpeg_binary, "-y", "-i", str(video_path), "-vn", "-c:a", "aac",
         "-ar", "48000", "-ac", "2", str(audio_path)],
        capture_output=True, timeout=120, check=False,
    )


def _build_open_card(db: Session, vp: VideoProject, w: int, h: int, fps: int, tmp: Path) -> dict | None:
    cfg = vp.open_config or {}
    text = cfg.get("text") or vp.name or "工程投标视频"
    sub_text = cfg.get("sub_text") or ""
    if not text and not sub_text:
        return None
    duration = max(1.0, float(cfg.get("duration", 3.0)))
    data = render_title_card(text, sub_text, duration=duration, width=w, height=h, fps=fps,
                             brand_color=cfg.get("brand_color") or vp.brand_color)
    video_path = tmp / "open.mp4"
    _write_bytes(video_path, data)
    audio_path = tmp / "open.m4a"
    _extract_audio(video_path, audio_path)
    return {"path": str(video_path), "audio_path": str(audio_path), "duration": duration,
            "transition_type": "fade", "transition_duration": 0.5, "shot_id": None}


def _build_close_card(db: Session, vp: VideoProject, w: int, h: int, fps: int, tmp: Path) -> dict | None:
    cfg = vp.close_config or {}
    text = cfg.get("text") or ""
    if not text:
        return None
    duration = max(1.0, float(cfg.get("duration", 3.0)))
    data = render_title_card(text, "投标人：企业承诺", duration=duration, width=w, height=h, fps=fps,
                             brand_color=vp.brand_color)
    video_path = tmp / "close.mp4"
    _write_bytes(video_path, data)
    audio_path = tmp / "close.m4a"
    _extract_audio(video_path, audio_path)
    return {"path": str(video_path), "audio_path": str(audio_path), "duration": duration,
            "transition_type": "fade", "transition_duration": 0.5, "shot_id": None}


def _write_bytes(path: Path, data: bytes) -> None:
    path.write_bytes(data)


# ============================================================
# 项目级 SRT（含转场时间轴）
# ============================================================

def _project_srt(db: Session, vp: VideoProject, items: list[dict], segs: list[VideoSegment]) -> str:
    """项目级字幕：按分段顺序累计，转场造成的时间重叠计入累计时间。"""
    all_subs: list[dict] = []
    offset = 0.0
    seg_by_shot = {s.storyboard_shot_id: s for s in segs}
    n = len(items)
    for idx, item in enumerate(items):
        shot_id = item.get("shot_id")
        seg = seg_by_shot.get(shot_id) if shot_id else None
        subs = []
        if seg:
            subs = resolve_subtitles(db, seg)
        if subs:
            for sub in subs:
                entry = dict(sub)
                entry["start_ms"] = int(round((offset + float(sub.get("start_ms", 0)) / 1000) * 1000))
                entry["end_ms"] = int(round((offset + float(sub.get("end_ms", 0)) / 1000) * 1000))
                all_subs.append(entry)
        # 移动到下一项：累计时长 - 本项之后的转场（最后一项无后续转场）
        this_trans = float(item.get("transition_duration", 0.0) or 0.0)
        offset += float(item["duration"]) - (this_trans if idx < n - 1 else 0.0)
    return render_srt(all_subs)


def _timeline_snapshot(vp: VideoProject, items: list[dict], segs: list[VideoSegment]) -> dict:
    return {
        "width": vp.width,
        "height": vp.height,
        "fps": vp.fps,
        "items": [
            {
                "shot_id": it.get("shot_id"),
                "duration": it["duration"],
                "transition_type": it["transition_type"],
                "transition_duration": it["transition_duration"],
            }
            for it in items
        ],
        "music_tracks": vp.music_tracks,
        "logo_config": vp.logo_config,
        "open_config": vp.open_config,
        "close_config": vp.close_config,
        "subtitle_style": vp.subtitle_style,
        "brand_color": vp.brand_color,
    }


def build_export_report(db: Session, vp: VideoProject, mode: str, preflight_result: dict, items: list[dict], total: float) -> dict:
    segs = (
        db.query(VideoSegment)
        .filter(VideoSegment.video_project_id == vp.id, VideoSegment.render_status != "skipped")
        .order_by(VideoSegment.sequence.asc())
        .all()
    )
    seg_details = []
    for seg in segs:
        shot = db.get(StoryboardShot, seg.storyboard_shot_id) if seg.storyboard_shot_id else None
        seg_details.append({
            "sequence": seg.sequence,
            "title": shot.title if shot else None,
            "duration": seg.duration,
            "render_status": seg.render_status,
            "visual_motion": seg.visual_motion,
            "fit_mode": seg.fit_mode,
            "transition_type": seg.transition_type,
            "subtitle_enabled": seg.subtitle_enabled,
            "volume": seg.volume,
        })
    return {
        "video_project_id": vp.id,
        "name": vp.name,
        "mode": mode,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_duration_seconds": round(total, 3),
        "segment_count": len(segs),
        "width": vp.width,
        "height": vp.height,
        "fps": vp.fps,
        "preflight": preflight_result,
        "segments": seg_details,
        "loudness_note": "目标约 -16 LUFS，True Peak 不高于 -1.5 dB；当前为简化峰值检查（未做广播级响度检测）。",
        "mock_mode": not settings.ai_keys_configured,
    }


# ============================================================
# 导出任务
# ============================================================

def create_export(db: Session, vp: VideoProject, mode: str, user: User | None = None) -> ExportTask:
    """创建导出任务（demo/formal），执行前检查。"""
    check = preflight(db, vp, mode)
    if mode == "formal" and not check["ok"]:
        errors = [i["message"] for i in check["issues"] if i["level"] == "error"]
        raise VideoProjectError("正式导出前检查未通过：" + "；".join(errors[:8]), check["issues"])

    et = ExportTask(
        video_project_id=vp.id,
        project_id=vp.project_id,
        export_format="mp4",
        mode=mode,
        status="queued",
        progress=0,
        params={"video_project_id": vp.id, "mode": mode},
    )
    db.add(et)
    db.flush()
    # 时间轴快照
    segs = db.query(VideoSegment).filter(VideoSegment.video_project_id == vp.id).order_by(VideoSegment.sequence.asc()).all()
    items = []
    for s in segs:
        items.append({"shot_id": s.storyboard_shot_id, "duration": s.duration,
                      "transition_type": s.transition_type, "transition_duration": s.transition_duration})
    snapshot = {
        "width": vp.width, "height": vp.height, "fps": vp.fps,
        "items": items, "music_tracks": vp.music_tracks, "logo_config": vp.logo_config,
        "open_config": vp.open_config, "close_config": vp.close_config,
        "subtitle_style": vp.subtitle_style, "brand_color": vp.brand_color,
    }
    et.timeline_snapshot = snapshot
    vp.timeline_snapshot = snapshot
    vp.status = "composing"
    db.commit()
    db.refresh(et)
    return et


def dispatch_export(db: Session, export_task: ExportTask) -> ExportTask:
    """导出任务分发：USE_CELERY 异步，否则同步。"""
    from app.tasks.video_export import compose_project_task, compose_project_sync

    if settings.use_celery:
        try:
            async_result = compose_project_task.delay(export_task.id)
            export_task.celery_task_id = async_result.id
            db.commit()
        except Exception as exc:
            logger.warning("celery_export_fallback_sync", error=str(exc))
            _run_export_sync(export_task.id)
    else:
        _run_export_sync(export_task.id)
    db.refresh(export_task)
    return export_task


def _run_export_sync(export_id: str) -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        et = db.get(ExportTask, export_id)
        if not et:
            return
        compose_project(db, export_id)
    except Exception as exc:
        db.rollback()
        et = db.get(ExportTask, export_id)
        if et:
            et.status = "failed"
            et.error_message = str(exc)[:2000]
            vp = db.get(VideoProject, et.video_project_id)
            if vp:
                vp.status = "failed"
            db.commit()
        logger.exception("export_failed", export_id=export_id)
    finally:
        db.close()


def refresh_render_batch_progress(db: Session, parent_id: str) -> RenderTask:
    """聚合批量分段渲染父任务进度（segment_render_all）。"""
    parent = db.get(RenderTask, parent_id)
    if not parent:
        raise VideoProjectError("批量任务不存在")
    children = db.query(RenderTask).filter(RenderTask.parent_task_id == parent_id).all()
    total = len(children)
    counts: dict[str, int] = {}
    for c in children:
        counts[c.status] = counts.get(c.status, 0) + 1
    done = counts.get("success", 0)
    failed = counts.get("failed", 0)
    cancelled = counts.get("cancelled", 0)
    parent.result = {
        "total": total, "success": done, "failed": failed,
        "cancelled": cancelled, "running": total - done - failed - cancelled,
    }
    if total and done + failed + cancelled >= total:
        parent.status = "success" if done > 0 else "failed"
        parent.progress = 100
        parent.message = f"分段渲染完成：成功 {done}，失败 {failed}"
    else:
        parent.status = "running"
        parent.progress = round((done + failed) / total * 100) if total else 0
        parent.message = f"分段渲染中：{done}/{total}"
    db.commit()
    db.refresh(parent)
    return parent
