"""统一 AI Provider 与业务环节配置。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ForbiddenError
from app.models.user import User
from app.schemas.ai_configuration import AIConfigurationUpdate
from app.services.ai_configuration import read_configuration, save_configuration

router = APIRouter(prefix="/settings", tags=["系统设置"])


def require_admin(current: User = Depends(get_current_user)) -> User:
    if not current.is_superuser:
        raise ForbiddenError("只有管理员可以修改 AI 服务配置")
    return current


@router.get("/ai", response_model=dict, summary="读取统一 AI 配置")
def get_ai_configuration(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return read_configuration(db)


@router.put("/ai", response_model=dict, summary="保存统一 AI 配置")
def update_ai_configuration(
    payload: AIConfigurationUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    return save_configuration(db, payload.model_dump(), current.username)
