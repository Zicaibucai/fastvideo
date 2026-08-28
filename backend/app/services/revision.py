"""并发编辑保护：基于 revision 的乐观锁。

更新请求可携带 `base_revision`（客户端读取时的版本号）。
若与服务器当前版本不一致，返回 409，并附带：
- server_revision：服务器当前版本
- base_revision：用户提交基于的版本
- server_updated_at：服务器版本最后更新时间
- message：可读冲突提示

未携带 base_revision 的请求按历史行为放行（向后兼容），
前端应始终在编辑类请求中携带以避免静默覆盖他人修改。
"""

from __future__ import annotations

from datetime import datetime

from app.core.exceptions import ConflictError


def check_revision(entity, base_revision: int | None) -> None:
    """校验乐观锁版本。entity 需有 revision 与 updated_at 属性。"""
    if base_revision is None:
        return
    current = getattr(entity, "revision", None) or 1
    if int(base_revision) != int(current):
        updated_at = getattr(entity, "updated_at", None)
        raise ConflictError(
            "该内容刚被其他成员修改，请加载最新版本后再保存（你的编辑内容请自行复制保留）",
            detail={
                "conflict": "revision",
                "server_revision": current,
                "base_revision": base_revision,
                "server_updated_at": (
                    updated_at.isoformat() if isinstance(updated_at, datetime) else None
                ),
            },
        )


def bump_revision(entity) -> None:
    entity.revision = (getattr(entity, "revision", None) or 1) + 1
