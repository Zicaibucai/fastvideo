"""配音模板路由。

- 项目级旧路由：/projects/{project_id}/voices（兼容）
- 全局路由：/voice/providers、/voice/templates 等
模板支持系统/企业/项目三级；系统模板普通用户不可删除。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.adapters.factory import get_tts_adapter, tts_provider_info
from app.api.deps import get_current_user
from app.core.database import get_db
from app.services.permissions import (
    get_project_access,
    PERM_DOCUMENT_EDIT,
    PERM_DOCUMENT_UPLOAD,
    PERM_DOCUMENT_VIEW,
    PERM_EXPORT_DEMO,
    PERM_EXPORT_FORMAL,
    PERM_EXPORT_VIEW,
    PERM_FACT_EDIT,
    PERM_FACT_VIEW,
    PERM_MEDIA_EDIT,
    PERM_MEDIA_VIEW,
    PERM_PROJECT_VIEW,
    PERM_SCORING_VIEW,
    PERM_STORYBOARD_EDIT,
    PERM_STORYBOARD_VIEW,
    PERM_VIDEO_EDIT,
    PERM_VIDEO_VIEW,
    PERM_VOICE_EDIT,
    PERM_VOICE_VIEW,
)
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.storage import storage
from app.models.asset import Asset
from app.models.project import Project
from app.models.user import User
from app.models.voice_template import VoiceTemplate
from app.schemas.voice import (
    VoiceTemplateCreate,
    VoiceTemplateOut,
    VoiceTemplateUpdate,
)
from app.services.audit import log_action

router = APIRouter(prefix="/projects/{project_id}/voices", tags=["配音模板"])
global_router = APIRouter(prefix="/voice", tags=["配音模板（全局）"])

SPEAKING_STYLES = [
    "正式稳重",
    "沉稳大气",
    "科技专业",
    "清晰客观",
    "亲和自然",
    "激昂有力",
    "新闻播报",
    "工程解说",
]


def _get_project(db: Session, project_id: str, user: User, permission: str = PERM_VOICE_VIEW) -> Project:
    """统一项目访问：成员校验 + 细粒度权限（非成员 404，权限不足 403）。"""
    return get_project_access(db, project_id, user, permission).project


def _get_template(db: Session, template_id: str, *, include_disabled: bool = True) -> VoiceTemplate:
    tpl = db.get(VoiceTemplate, template_id)
    if not tpl:
        raise NotFoundError("配音模板不存在")
    if not include_disabled and not tpl.is_enabled:
        raise NotFoundError("配音模板已停用")
    return tpl


def _check_editable(tpl: VoiceTemplate, user: User) -> None:
    """系统模板普通用户不可删除/修改。"""
    if tpl.is_system and not user.is_superuser:
        raise ForbiddenError("系统内置配音模板仅管理员可修改。")


def _payload_to_model(payload: VoiceTemplateCreate) -> dict:
    data = payload.model_dump(exclude_unset=True)
    # 兼容旧字段 gender → gender_style
    if data.get("gender") and not data.get("gender_style"):
        data["gender_style"] = data["gender"]
    data.pop("gender", None)
    return data


def _to_out(tpl: VoiceTemplate) -> VoiceTemplateOut:
    return VoiceTemplateOut(
        id=tpl.id,
        project_id=tpl.project_id,
        name=tpl.name,
        description=tpl.description,
        voice_provider=tpl.voice_provider,
        voice_name=tpl.voice_name,
        provider_voice_id=tpl.provider_voice_id,
        model_name=tpl.model_name,
        language=tpl.language,
        gender=tpl.gender,
        gender_style=tpl.gender_style,
        age_style=tpl.age_style,
        speaking_style=tpl.speaking_style,
        style=tpl.style,
        speed=tpl.speed,
        pitch=tpl.pitch,
        volume=tpl.volume,
        pause_strength=tpl.pause_strength,
        emotion=tpl.emotion,
        sample_rate=tpl.sample_rate,
        audio_format=tpl.audio_format,
        pronunciation_profile_id=tpl.pronunciation_profile_id,
        authorization_type=tpl.authorization_type,
        authorization_status=tpl.authorization_status,
        authorization_note=tpl.authorization_note,
        authorization_expire_at=tpl.authorization_expire_at,
        preview_asset_id=tpl.preview_asset_id,
        preview_text=tpl.preview_text,
        is_default=tpl.is_default,
        is_system=tpl.is_system,
        is_enabled=tpl.is_enabled,
        sort_order=tpl.sort_order,
        created_by=tpl.created_by,
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    )


# ============================================================
# 项目级路由（兼容旧前端）
# ============================================================

@router.get("", response_model=list[VoiceTemplateOut], summary="配音模板列表（项目）")
def list_voices(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[VoiceTemplate]:
    _get_project(db, project_id, current, PERM_VOICE_VIEW)
    return (
        db.query(VoiceTemplate)
        .filter((VoiceTemplate.project_id == project_id) | VoiceTemplate.is_system)
        .order_by(VoiceTemplate.sort_order.asc(), VoiceTemplate.created_at.desc())
        .all()
    )


@router.post("", response_model=VoiceTemplateOut, status_code=201, summary="创建配音模板（项目）")
def create_voice(
    project_id: str,
    payload: VoiceTemplateCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VoiceTemplate:
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    if payload.is_system and not current.is_superuser:
        raise ForbiddenError("普通用户不能创建系统模板。")
    data = _payload_to_model(payload)
    data["project_id"] = project_id
    data["created_by"] = current.username
    v = VoiceTemplate(**data)
    db.add(v)
    db.commit()
    db.refresh(v)
    log_action(db, user=current, project_id=project_id, action="voice_template_create",
               entity_type="voice_template", entity_id=v.id, commit=True)
    return v


@router.patch("/{voice_id}", response_model=VoiceTemplateOut, summary="更新配音模板")
def update_voice(
    project_id: str,
    voice_id: str,
    payload: VoiceTemplateUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VoiceTemplate:
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    v = _get_template(db, voice_id)
    _check_editable(v, current)
    data = payload.model_dump(exclude_unset=True)
    if data.get("gender") and not data.get("gender_style"):
        data["gender_style"] = data["gender"]
    data.pop("gender", None)
    for field, value in data.items():
        setattr(v, field, value)
    db.commit()
    db.refresh(v)
    log_action(db, user=current, project_id=project_id, action="voice_template_update",
               entity_type="voice_template", entity_id=v.id, commit=True)
    return v


@router.delete("/{voice_id}", status_code=204, summary="删除配音模板")
def delete_voice(
    project_id: str,
    voice_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _get_project(db, project_id, current, PERM_VOICE_EDIT)
    v = _get_template(db, voice_id)
    _check_editable(v, current)
    db.delete(v)
    db.commit()
    log_action(db, user=current, project_id=project_id, action="voice_template_delete",
               entity_type="voice_template", entity_id=voice_id, commit=True)


# ============================================================
# 全局路由
# ============================================================

@global_router.get("/speaking-styles", response_model=list[str], summary="说话风格预设")
def speaking_styles() -> list[str]:
    return SPEAKING_STYLES


@global_router.get("/providers", response_model=list, summary="TTS Provider 列表")
def list_providers() -> list:
    return tts_provider_info()


@global_router.get("/providers/{provider}/capabilities", response_model=dict, summary="Provider 能力")
def provider_capabilities(provider: str) -> dict:
    adapter = get_tts_adapter()
    if provider in ("mock", "disabled", adapter.provider):
        return adapter.capabilities()
    return {cap: False for cap in _ALL_TTS_CAP_KEYS}


_ALL_TTS_CAP_KEYS = [
    "synthesize", "ssml", "timestamps", "word_timestamps", "sentence_timestamps",
    "speed_control", "pitch_control", "volume_control", "emotion", "streaming",
    "voice_preview", "mp3", "wav", "voice_cloning",
]


@global_router.get("/providers/{provider}/voices", response_model=list, summary="音色列表")
def provider_voices(provider: str, db: Session = Depends(get_db), current: User = Depends(get_current_user)) -> list:
    adapter = get_tts_adapter()
    if provider in ("mock", "disabled", adapter.provider):
        return adapter.list_voices()
    return []


@global_router.get("/templates", response_model=list[VoiceTemplateOut], summary="模板列表（全局）")
def list_global_templates(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[VoiceTemplate]:
    return (
        db.query(VoiceTemplate)
        .filter(VoiceTemplate.is_enabled.is_(True))
        .order_by(VoiceTemplate.is_system.desc(), VoiceTemplate.sort_order.asc())
        .all()
    )


@global_router.post("/templates", response_model=VoiceTemplateOut, status_code=201, summary="创建模板（全局）")
def create_global_template(
    payload: VoiceTemplateCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VoiceTemplate:
    if (payload.is_system or payload.voice_provider in ("provider", "enterprise")) and not current.is_superuser:
        raise ForbiddenError("仅管理员可创建系统/企业模板。")
    data = _payload_to_model(payload)
    data["project_id"] = None if data.get("is_system") else data.get("project_id")
    data["created_by"] = current.username
    v = VoiceTemplate(**data)
    db.add(v)
    db.commit()
    db.refresh(v)
    log_action(db, user=current, project_id=v.project_id, action="voice_template_create",
               entity_type="voice_template", entity_id=v.id, commit=True)
    return v


@global_router.get("/templates/{template_id}", response_model=VoiceTemplateOut, summary="模板详情")
def get_template(
    template_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VoiceTemplate:
    return _get_template(db, template_id)


@global_router.patch("/templates/{template_id}", response_model=VoiceTemplateOut, summary="更新模板")
def update_global_template(
    template_id: str,
    payload: VoiceTemplateUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VoiceTemplate:
    v = _get_template(db, template_id)
    _check_editable(v, current)
    data = payload.model_dump(exclude_unset=True)
    if data.get("gender") and not data.get("gender_style"):
        data["gender_style"] = data["gender"]
    data.pop("gender", None)
    for field, value in data.items():
        setattr(v, field, value)
    db.commit()
    db.refresh(v)
    log_action(db, user=current, project_id=v.project_id, action="voice_template_update",
               entity_type="voice_template", entity_id=v.id, commit=True)
    return v


@global_router.delete("/templates/{template_id}", status_code=204, summary="删除模板")
def delete_global_template(
    template_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    v = _get_template(db, template_id)
    _check_editable(v, current)
    db.delete(v)
    db.commit()
    log_action(db, user=current, project_id=v.project_id, action="voice_template_delete",
               entity_type="voice_template", entity_id=template_id, commit=True)


@global_router.post("/templates/{template_id}/duplicate", response_model=VoiceTemplateOut, summary="复制模板")
def duplicate_template(
    template_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VoiceTemplate:
    src = _get_template(db, template_id)
    clone = VoiceTemplate(
        project_id=src.project_id,
        name=f"{src.name}（副本）",
        description=src.description,
        voice_provider=src.voice_provider,
        voice_name=src.voice_name,
        provider_voice_id=src.provider_voice_id,
        model_name=src.model_name,
        language=src.language,
        gender=src.gender,
        gender_style=src.gender_style,
        age_style=src.age_style,
        speaking_style=src.speaking_style,
        style=src.style,
        speed=src.speed,
        pitch=src.pitch,
        volume=src.volume,
        pause_strength=src.pause_strength,
        emotion=src.emotion,
        sample_rate=src.sample_rate,
        audio_format=src.audio_format,
        pronunciation_profile_id=src.pronunciation_profile_id,
        authorization_type=src.authorization_type,
        authorization_status=src.authorization_status,
        authorization_note=src.authorization_note,
        is_default=False,
        is_system=False,
        is_enabled=True,
        created_by=current.username,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    log_action(db, user=current, project_id=clone.project_id, action="voice_template_duplicate",
               entity_type="voice_template", entity_id=clone.id,
               detail={"source_id": template_id}, commit=True)
    return clone


@global_router.post("/templates/{template_id}/preview", response_model=dict, summary="试听音色")
def preview_template(
    template_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    v = _get_template(db, template_id)
    adapter = get_tts_adapter()
    if not adapter.supports("voice_preview"):
        raise ConflictError("当前 Provider 不支持试听。")
    sample = v.preview_text or "这是音色试听，用于投标视频配音。"
    data = adapter.preview_voice(voice=v.effective_voice_id, text=sample, format="mp3")

    key = f"voice/previews/{uuid.uuid4().hex}.mp3"
    storage.save(key, data)
    asset = Asset(
        project_id=v.project_id,
        name=f"试听-{v.name}",
        asset_type="audio",
        source="ai_tts",
        file_key=key,
        file_size=len(data),
        mime_type="audio/mpeg",
        is_ai_generated=adapter.provider != "mock",
        ai_disclaimer="Mock Audio：演示合成音。" if adapter.provider == "mock" else None,
        generated_by=adapter.provider,
        prompt=sample,
        meta={"voice_template_id": v.id, "voice_id": v.effective_voice_id},
    )
    db.add(asset)
    db.flush()
    v.preview_asset_id = asset.id
    db.commit()

    log_action(db, user=current, project_id=v.project_id, action="voice_preview",
               entity_type="voice_template", entity_id=v.id, commit=True)
    return {"asset_id": asset.id, "url": f"/files/{key}", "is_mock": adapter.provider == "mock"}


def seed_default_voice_templates(db: Session, project_id: str | None = None) -> None:
    """创建系统默认配音模板（首次调用）。"""
    existing = db.query(VoiceTemplate).filter(VoiceTemplate.is_system.is_(True)).count()
    if existing > 0:
        return
    defaults = [
        {
            "name": "工程解说·沉稳大气",
            "voice_name": "onyx",
            "provider_voice_id": "onyx",
            "gender": "male",
            "gender_style": "male",
            "style": "沉稳大气",
            "speaking_style": "沉稳大气",
            "voice_provider": "disabled",
            "speed": 1.0,
            "pause_strength": 1.0,
            "is_system": True,
            "sort_order": 1,
            "authorization_type": "provider_builtin",
            "authorization_status": "approved",
        },
        {
            "name": "正式稳重",
            "voice_name": "echo",
            "provider_voice_id": "echo",
            "gender": "male",
            "gender_style": "male",
            "speaking_style": "正式稳重",
            "voice_provider": "disabled",
            "speed": 0.95,
            "pause_strength": 1.1,
            "is_system": True,
            "sort_order": 2,
            "authorization_type": "provider_builtin",
            "authorization_status": "approved",
        },
        {
            "name": "科技专业",
            "voice_name": "alloy",
            "provider_voice_id": "alloy",
            "gender": "neutral",
            "gender_style": "neutral",
            "speaking_style": "科技专业",
            "voice_provider": "disabled",
            "speed": 1.05,
            "pause_strength": 0.9,
            "is_system": True,
            "sort_order": 3,
            "authorization_type": "provider_builtin",
            "authorization_status": "approved",
        },
        {
            "name": "亲和自然",
            "voice_name": "nova",
            "provider_voice_id": "nova",
            "gender": "female",
            "gender_style": "female",
            "speaking_style": "亲和自然",
            "voice_provider": "disabled",
            "speed": 1.0,
            "pause_strength": 1.0,
            "is_system": True,
            "sort_order": 4,
            "authorization_type": "provider_builtin",
            "authorization_status": "approved",
        },
        {
            "name": "新闻播报",
            "voice_name": "shimmer",
            "provider_voice_id": "shimmer",
            "gender": "female",
            "gender_style": "female",
            "speaking_style": "新闻播报",
            "voice_provider": "disabled",
            "speed": 1.1,
            "pause_strength": 0.8,
            "is_system": True,
            "sort_order": 5,
            "authorization_type": "provider_builtin",
            "authorization_status": "approved",
        },
        {
            "name": "激昂有力",
            "voice_name": "fable",
            "provider_voice_id": "fable",
            "gender": "male",
            "gender_style": "male",
            "speaking_style": "激昂有力",
            "voice_provider": "disabled",
            "speed": 1.05,
            "pause_strength": 0.9,
            "is_system": True,
            "sort_order": 6,
            "authorization_type": "provider_builtin",
            "authorization_status": "approved",
        },
    ]
    for item in defaults:
        db.add(VoiceTemplate(**item))
    db.commit()


# 火山引擎豆包语音合成 2.0 音色模板（provider=volcengine）
VOLCENGINE_VOICE_TEMPLATES = [
    {
        "name": "豆包·小何（女声·默认）",
        "voice_name": "zh_female_xiaohe_uranus_bigtts",
        "provider_voice_id": "zh_female_xiaohe_uranus_bigtts",
        "gender": "female",
        "gender_style": "female",
        "speaking_style": "正式稳重",
        "voice_provider": "volcengine",
        "speed": 1.0,
        "pause_strength": 1.0,
        "is_system": True,
        "sort_order": 101,
        "authorization_type": "provider_builtin",
        "authorization_status": "approved",
    },
    {
        "name": "豆包·云舟（男声·解说）",
        "voice_name": "zh_male_m191_uranus_bigtts",
        "provider_voice_id": "zh_male_m191_uranus_bigtts",
        "gender": "male",
        "gender_style": "male",
        "speaking_style": "沉稳大气",
        "voice_provider": "volcengine",
        "speed": 1.0,
        "pause_strength": 1.0,
        "is_system": True,
        "sort_order": 102,
        "authorization_type": "provider_builtin",
        "authorization_status": "approved",
    },
    {
        "name": "豆包·灿灿（女声·温暖叙事）",
        "voice_name": "zh_female_cancan_uranus_bigtts",
        "provider_voice_id": "zh_female_cancan_uranus_bigtts",
        "gender": "female",
        "gender_style": "female",
        "speaking_style": "亲和自然",
        "voice_provider": "volcengine",
        "speed": 1.0,
        "pause_strength": 1.0,
        "is_system": True,
        "sort_order": 103,
        "authorization_type": "provider_builtin",
        "authorization_status": "approved",
    },
    {
        "name": "豆包·小天（男声·稳重）",
        "voice_name": "zh_male_taocheng_uranus_bigtts",
        "provider_voice_id": "zh_male_taocheng_uranus_bigtts",
        "gender": "male",
        "gender_style": "male",
        "speaking_style": "正式稳重",
        "voice_provider": "volcengine",
        "speed": 0.98,
        "pause_strength": 1.05,
        "is_system": True,
        "sort_order": 104,
        "authorization_type": "provider_builtin",
        "authorization_status": "approved",
    },
    {
        "name": "豆包·儒雅才俊 2.0（男声·深沉解说）",
        "voice_name": "ICL_uranus_zh_male_ruyacaijun_tob",
        "provider_voice_id": "ICL_uranus_zh_male_ruyacaijun_tob",
        "gender": "male",
        "gender_style": "male",
        "speaking_style": "深沉解说",
        "voice_provider": "volcengine",
        "speed": 0.98,
        "pause_strength": 1.05,
        "is_system": True,
        "sort_order": 106,
        "authorization_type": "provider_builtin",
        "authorization_status": "approved",
    },
    {
        "name": "豆包·高冷御姐（女声·冷静）",
        "voice_name": "zh_female_gaolengyujie_uranus_bigtts",
        "provider_voice_id": "zh_female_gaolengyujie_uranus_bigtts",
        "gender": "female",
        "gender_style": "female",
        "speaking_style": "科技专业",
        "voice_provider": "volcengine",
        "speed": 1.0,
        "pause_strength": 1.0,
        "is_system": True,
        "sort_order": 105,
        "authorization_type": "provider_builtin",
        "authorization_status": "approved",
    },
]


def seed_volcengine_voice_templates(db: Session) -> None:
    """幂等补充火山引擎豆包语音合成音色模板（按名称查找，不重复创建）。"""
    for item in VOLCENGINE_VOICE_TEMPLATES:
        exists = (
            db.query(VoiceTemplate)
            .filter(
                VoiceTemplate.is_system.is_(True),
                VoiceTemplate.name == item["name"],
            )
            .first()
        )
        if exists:
            continue
        db.add(VoiceTemplate(**item))
    db.commit()
