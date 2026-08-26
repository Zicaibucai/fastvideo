"""评分点服务：从评分办法文档提取评分点，计算分镜覆盖率。"""

from __future__ import annotations

import re
from typing import Any

from app.core.logging import get_logger
from app.models.scoring_point import ScoringPoint
from app.models.storyboard_shot import StoryboardShot

logger = get_logger(__name__)

# 常见评分项关键词 → 分类
SCORING_KEYWORDS = [
    ("投标报价", "价格"),
    ("施工组织设计", "施工方案"),
    ("施工方案", "施工方案"),
    ("进度计划", "施工方案"),
    ("质量保证", "质量"),
    ("质量管理", "质量"),
    ("安全管理", "安全"),
    ("文明施工", "安全"),
    ("绿色施工", "绿色"),
    ("BIM", "BIM"),
    ("信息化", "BIM"),
    ("项目班子", "团队"),
    ("项目经理", "团队"),
    ("业绩", "资信"),
    ("信用", "资信"),
    ("财务状况", "资信"),
    ("服务承诺", "服务"),
    ("售后", "服务"),
]


def extract_scoring_points(db, document_id: str, project_id: str, pages: list[Any]) -> int:
    """从评分办法类文档提取评分点，写入 scoring_points 表。

    策略：在页面文本中查找包含"分值/分/得分"关键词的句子，识别标题层级，
    按"评分项 + 分值"组合建立评分点。
    """
    text_blocks: list[tuple[int, str, str | None]] = []  # (page, text, heading)
    for page in pages:
        text = getattr(page, "cleaned_text", None) or ""
        if not text:
            continue
        text_blocks.append((page.page_number, text, getattr(page, "location_label", None)))

    # 已有评分点清空重建（避免重复）
    existing = db.query(ScoringPoint).filter(
        ScoringPoint.project_id == project_id,
        ScoringPoint.source_document_id == document_id,
    ).all()
    for e in existing:
        db.delete(e)
    db.flush()

    count = 0
    for page_no, text, _loc in text_blocks:
        # 按行分析
        for line in text.splitlines():
            s = line.strip()
            if len(s) < 4 or len(s) > 200:
                continue
            has_score = re.search(r"([0-9]{1,2}(?:\.5)?)\s*分", s) or re.search(r"满分\s*([0-9]{1,2})", s)
            has_keyword = any(kw in s for kw, _ in SCORING_KEYWORDS)
            if not (has_score and has_keyword):
                continue

            # 提取分值
            score = None
            m = re.search(r"([0-9]{1,2}(?:\.5)?)\s*分", s)
            if m:
                score = float(m.group(1))
            else:
                m = re.search(r"满分\s*([0-9]{1,2})", s)
                if m:
                    score = float(m.group(1))

            # 提取标题：去掉分值后缀
            title = re.sub(r"[：:].*$", "", s).strip()
            if len(title) > 50:
                title = title[:50]

            # 分类
            category = None
            for kw, cat in SCORING_KEYWORDS:
                if kw in s:
                    category = cat
                    break

            # 截取原文
            quote = s[:200]

            point = ScoringPoint(
                project_id=project_id,
                source_document_id=document_id,
                source_page=page_no,
                title=title or f"评分项{count + 1}",
                description=s[:500],
                score=score,
                category=category,
                source_quote=quote,
                matched_shot_ids=[],
            )
            db.add(point)
            count += 1

    db.commit()
    logger.info("scoring_points_extracted", document_id=document_id, count=count)
    return count


def _safe_match(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords if kw)


def compute_scoring_coverage(db, project_id: str) -> dict:
    """计算评分点覆盖率：每个评分点被哪些分镜覆盖。"""
    points = db.query(ScoringPoint).filter(ScoringPoint.project_id == project_id).all()
    shots = db.query(StoryboardShot).filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True)).all()

    # 建立分镜关键词索引
    shot_keywords: list[tuple[StoryboardShot, str]] = []
    for shot in shots:
        text = f"{shot.title or ''} {shot.narration or ''}"
        shot_keywords.append((shot, text))

    for point in points:
        point_keywords = [kw for kw, _ in SCORING_KEYWORDS if kw in (point.title or "") or kw in (point.category or "")]
        matched: list[str] = []
        for shot, text in shot_keywords:
            if not point_keywords:
                # 无关键词时按标题包含匹配
                if point.title and shot.title and point.title in shot.title:
                    matched.append(shot.id)
            elif _safe_match(text, point_keywords):
                matched.append(shot.id)
        point.matched_shot_ids = matched

    db.commit()

    covered = sum(1 for p in points if p.matched_shot_ids)
    total = len(points)
    return {
        "total": total,
        "covered": covered,
        "coverage_rate": round(covered / total, 3) if total else 0.0,
        "points": points,
    }


def ensure_scoring_points(db, project_id: str) -> None:
    """确保项目至少有一组评分点（演示用种子，若无评分办法文档）。"""
    count = db.query(ScoringPoint).filter(ScoringPoint.project_id == project_id).count()
    if count > 0:
        return

    defaults = [
        {"title": "施工组织设计", "score": 20, "category": "施工方案", "description": "施工方案的科学性、合理性、针对性"},
        {"title": "施工进度计划", "score": 10, "category": "施工方案", "description": "进度计划的合理性及保证措施"},
        {"title": "质量保证措施", "score": 15, "category": "质量", "description": "质量目标与质量保证体系"},
        {"title": "安全文明施工", "score": 10, "category": "安全", "description": "安全文明施工保证措施"},
        {"title": "绿色施工与BIM", "score": 10, "category": "BIM", "description": "绿色施工、BIM 技术应用"},
        {"title": "项目班子配置", "score": 10, "category": "团队", "description": "项目经理及项目班子资历与配置"},
        {"title": "企业业绩与信誉", "score": 15, "category": "资信", "description": "企业类似工程业绩与信用"},
        {"title": "投标报价", "score": 10, "category": "价格", "description": "投标报价合理性"},
    ]
    for item in defaults:
        db.add(
            ScoringPoint(
                project_id=project_id,
                title=item["title"],
                score=item["score"],
                category=item["category"],
                description=item["description"],
                matched_shot_ids=[],
            )
        )
    db.commit()
