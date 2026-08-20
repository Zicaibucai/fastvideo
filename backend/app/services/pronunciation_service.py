"""发音词典服务（PronunciationService）。

管理 PronunciationProfile / PronunciationRule：
- 系统 / 企业 / 项目三级词典，项目优先级最高
- 规则 CRUD、导入导出 JSON、朗读测试
- 正则表达式安全校验（ReDoS 防护）
- 普通用户不得修改系统词典
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.pronunciation import PronunciationProfile, PronunciationRule
from app.services.narration_normalizer import normalize_narration

logger = get_logger(__name__)

# scope 顺序（数值越小优先级越高）
_SCOPE_ORDER = {"project": 0, "enterprise": 1, "system": 2}

# 危险正则启发式标记
_DANGEROUS_PATTERNS = [
    r"\(\?:?[^()]*[*+][*+?]",  # (?:...++) 嵌套量词
    r"\(\?:?[^()]*\{[0-9,]+\}[*+?]",
    r"\([^()]*[|][^()]*\)[+*]",  # (a|b)+ 交替量词
    r"\([^()]*[*+?]\)[*+]",  # (a+)+ / (a*)* 分组外再量词
    r"[^\\][*+?]\{",  # x+{ ... }
    r"\{[0-9]+\}\{[0-9]+\}",
    r"[.][*+][.][*+]",  # .*.* / .+.+
]

_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_PATTERNS))

MAX_RULE_LENGTH = 200
MAX_RULE_BODY = 500


def validate_regex(expr: str) -> None:
    """校验正则安全：不合法或可能 ReDoS 的表达式直接拒绝。"""
    if not expr:
        return
    if len(expr) > MAX_RULE_LENGTH:
        raise ConflictError("正则表达式过长，已拒绝。")
    try:
        re.compile(expr)
    except re.error as exc:
        raise ConflictError(f"正则表达式无效：{exc}")
    if _DANGEROUS_RE.search(expr):
        raise ConflictError("检测到可能造成拒绝服务的危险正则表达式，已拒绝。")


def get_effective_rules(db: Session, project_id: str | None) -> list[PronunciationRule]:
    """返回启用的发音规则，按 scope 优先级排序（project > enterprise > system），
    同 scope 内 priority 数值大者优先。"""
    query = db.query(PronunciationRule).filter(PronunciationRule.enabled.is_(True))
    if project_id:
        query = query.filter(
            (PronunciationRule.project_id == project_id)
            | (PronunciationRule.scope == "system")
        )
    else:
        query = query.filter(PronunciationRule.scope == "system")
    rules = query.order_by(PronunciationRule.scope.asc(), PronunciationRule.priority.desc()).all()
    return sorted(
        rules,
        key=lambda r: (_SCOPE_ORDER.get(r.scope, 9), -r.priority),
    )


def test_read(
    db: Session,
    project_id: str | None,
    text: str,
    rules: list[PronunciationRule] | None = None,
) -> dict[str, Any]:
    """测试朗读文本：返回规范化结果、命中规则与警告。"""
    effective = rules if rules is not None else get_effective_rules(db, project_id)
    result = normalize_narration(text, effective)
    matched = []
    for snap in result.pronunciation_snapshot:
        if snap.get("rule_id"):
            matched.append(snap)
    return {
        "original_text": result.original_text,
        "normalized_text": result.normalized_text,
        "pronunciation_snapshot": result.pronunciation_snapshot,
        "matched_rules": matched,
        "warnings": result.warnings,
    }


def _check_admin_for_system(db: Session, rule_id: str, is_superuser: bool) -> None:
    rule = db.get(PronunciationRule, rule_id)
    if rule and rule.scope == "system" and not is_superuser:
        raise ConflictError("普通用户不得修改系统词典。")


def create_rule(
    db: Session,
    *,
    project_id: str | None,
    source_text: str,
    spoken_text: str,
    rule_type: str = "literal",
    priority: int = 100,
    is_regex: bool = False,
    scope: str = "project",
    language: str = "zh-CN",
    created_by: str | None = None,
    profile_id: str | None = None,
    is_superuser: bool = False,
) -> PronunciationRule:
    if scope == "system" and not is_superuser:
        raise ConflictError("普通用户不得创建系统词典规则。")
    if not source_text or not spoken_text:
        raise ConflictError("源文本与朗读文本不能为空。")
    if len(source_text) > MAX_RULE_BODY or len(spoken_text) > MAX_RULE_BODY:
        raise ConflictError(f"规则文本长度不能超过 {MAX_RULE_BODY} 字符。")
    if is_regex:
        validate_regex(source_text)
    rule = PronunciationRule(
        project_id=project_id,
        profile_id=profile_id,
        source_text=source_text,
        spoken_text=spoken_text,
        language=language,
        rule_type=rule_type,
        priority=priority,
        is_regex=is_regex,
        enabled=True,
        scope=scope,
        created_by=created_by,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_rule(
    db: Session,
    rule_id: str,
    data: dict[str, Any],
    *,
    is_superuser: bool = False,
) -> PronunciationRule:
    _check_admin_for_system(db, rule_id, is_superuser)
    rule = db.get(PronunciationRule, rule_id)
    if not rule:
        raise NotFoundError("发音规则不存在")
    if "scope" in data and data["scope"] == "system" and not is_superuser:
        raise ConflictError("普通用户不得把规则改为系统级。")
    if data.get("is_regex") and data.get("source_text"):
        validate_regex(data["source_text"])
    for field, value in data.items():
        if hasattr(rule, field):
            setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule_id: str, *, is_superuser: bool = False) -> None:
    _check_admin_for_system(db, rule_id, is_superuser)
    rule = db.get(PronunciationRule, rule_id)
    if not rule:
        raise NotFoundError("发音规则不存在")
    db.delete(rule)
    db.commit()


# ---------------- Profile ----------------

def get_or_create_project_profile(db: Session, project_id: str, created_by: str | None = None) -> PronunciationProfile:
    """获取项目发音词典，不存在则创建。"""
    profile = (
        db.query(PronunciationProfile)
        .filter(PronunciationProfile.project_id == project_id, PronunciationProfile.scope == "project")
        .first()
    )
    if profile:
        return profile
    profile = PronunciationProfile(
        project_id=project_id,
        name="项目发音词典",
        description="本项目自定义朗读规则",
        language="zh-CN",
        scope="project",
        is_system=False,
        is_enabled=True,
        created_by=created_by,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def list_profiles(db: Session, project_id: str | None = None) -> list[PronunciationProfile]:
    query = db.query(PronunciationProfile).order_by(PronunciationProfile.scope.asc())
    if project_id:
        query = query.filter(
            (PronunciationProfile.project_id == project_id)
            | (PronunciationProfile.scope == "system")
        )
    return query.all()


def list_rules(db: Session, project_id: str | None, profile_id: str | None = None) -> list[PronunciationRule]:
    query = db.query(PronunciationRule).order_by(
        PronunciationRule.scope.asc(),
        PronunciationRule.priority.desc(),
        PronunciationRule.created_at.asc(),
    )
    if project_id:
        query = query.filter(
            (PronunciationRule.project_id == project_id)
            | (PronunciationRule.scope == "system")
        )
    if profile_id:
        query = query.filter(PronunciationRule.profile_id == profile_id)
    return query.all()


# ---------------- 导入导出 ----------------

def export_rules_json(db: Session, project_id: str) -> dict[str, Any]:
    rules = list_rules(db, project_id)
    return {
        "version": 1,
        "project_id": project_id,
        "rules": [
            {
                "source_text": r.source_text,
                "spoken_text": r.spoken_text,
                "language": r.language,
                "rule_type": r.rule_type,
                "priority": r.priority,
                "is_regex": r.is_regex,
                "scope": r.scope,
            }
            for r in rules
            if r.scope != "system" or True  # 包含系统只读信息，但导入时跳过 system
        ],
    }


def import_rules_json(
    db: Session,
    project_id: str,
    data: dict[str, Any],
    *,
    created_by: str | None = None,
    is_superuser: bool = False,
) -> dict[str, Any]:
    """导入 JSON 规则。跳过 system 级条目（只读）。返回导入统计。"""
    items = data.get("rules", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ConflictError("导入数据格式错误：需要 rules 列表。")
    if len(items) > 500:
        raise ConflictError("单次导入最多 500 条规则。")
    profile = get_or_create_project_profile(db, project_id, created_by)
    created = 0
    skipped = 0
    errors: list[str] = []
    for item in items:
        try:
            scope = item.get("scope", "project")
            if scope == "system":
                skipped += 1
                continue
            create_rule(
                db,
                project_id=project_id,
                source_text=str(item["source_text"]),
                spoken_text=str(item["spoken_text"]),
                rule_type=item.get("rule_type", "literal"),
                priority=int(item.get("priority", 100)),
                is_regex=bool(item.get("is_regex", False)),
                scope=scope,
                language=item.get("language", "zh-CN"),
                created_by=created_by,
                profile_id=profile.id,
                is_superuser=is_superuser,
            )
            created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{item.get('source_text', '?')}: {exc}")
    return {"created": created, "skipped": skipped, "errors": errors}


def detect_conflicts(db: Session, project_id: str | None, source_text: str) -> list[dict]:
    """检测与现有规则冲突的条目（相同 source_text 不同朗读）。"""
    rules = get_effective_rules(db, project_id)
    hits = [r for r in rules if r.source_text == source_text and r.enabled]
    return [
        {
            "rule_id": r.id,
            "source_text": r.source_text,
            "spoken_text": r.spoken_text,
            "scope": r.scope,
            "priority": r.priority,
        }
        for r in hits
    ]


def seed_system_pronunciation(db: Session) -> None:
    """创建系统发音词典（幂等）。"""
    profile = (
        db.query(PronunciationProfile)
        .filter(PronunciationProfile.scope == "system")
        .first()
    )
    if profile:
        return
    profile = PronunciationProfile(
        project_id=None,
        name="系统发音词典",
        description="内置工程术语朗读规则",
        language="zh-CN",
        scope="system",
        is_system=True,
        is_enabled=True,
        created_by="system",
    )
    db.add(profile)
    db.flush()
    builtin = [
        ("BIM", "BIM", "abbreviation"),
        ("EPC", "EPC", "abbreviation"),
        ("PC", "PC", "abbreviation"),
        ("MEP", "MEP", "abbreviation"),
        ("CAD", "CAD", "abbreviation"),
    ]
    for src, spoken, rtype in builtin:
        db.add(
            PronunciationRule(
                profile_id=profile.id,
                source_text=src,
                spoken_text=spoken,
                language="zh-CN",
                rule_type=rtype,
                priority=100,
                is_regex=False,
                enabled=True,
                scope="system",
                created_by="system",
            )
        )
    db.commit()
