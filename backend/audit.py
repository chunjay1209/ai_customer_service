"""审计日志工具模块。

提供统一的日志记录函数，供各 API 端点调用。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from . import models


def log(
    db: Session,
    *,
    tenant_code: str = "",
    username: str = "",
    role: str = "",
    action: str = "",
    target: str = "",
    detail: Optional[dict] = None,
    ip_address: str = "",
) -> models.AuditLog:
    """记录一条审计日志。

    Args:
        db: 数据库会话
        tenant_code: 商户代码
        username: 操作用户名
        role: 角色名
        action: 操作类型（login/logout/price_check/dashboard_view/user_create/user_update/user_delete/role_create/role_update/role_delete）
        target: 操作对象（用户名/角色名/查询文本片段）
        detail: 扩展详情 dict
        ip_address: IP 地址
    """
    entry = models.AuditLog(
        tenant_code=tenant_code or "",
        username=username or "",
        role=role or "",
        action=action or "",
        target=target or "",
        detail_json=json.dumps(detail or {}, ensure_ascii=False, default=str)[:8192],
        ip_address=ip_address or "",
    )
    db.add(entry)
    db.commit()
    return entry


def log_query(
    db: Session,
    tenant_code: str,
    username: str,
    role: str,
    query_text: str,
    match_count: int = 0,
) -> models.AuditLog:
    """快捷记录一条查价/看板查询。"""
    return log(
        db,
        tenant_code=tenant_code,
        username=username,
        role=role,
        action="price_check" if "/api/price/check" in query_text else "dashboard_view",
        target=(query_text or "")[:200],
        detail={"match_count": match_count},
    )


def get_logs(
    db: Session,
    tenant_code: str = "",
    action: str = "",
    username: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[models.AuditLog], int]:
    """分页查询审计日志，返回 (结果列表, 总数)。

    date_from / date_to: ISO 格式日期字符串，如 "2026-06-01"
    """
    from datetime import datetime as dt
    q = db.query(models.AuditLog)
    if tenant_code:
        q = q.filter(models.AuditLog.tenant_code == tenant_code)
    if action:
        q = q.filter(models.AuditLog.action == action)
    if username:
        q = q.filter(models.AuditLog.username == username)
    if date_from:
        try:
            df = dt.strptime(date_from.strip(), "%Y-%m-%d")
            q = q.filter(models.AuditLog.created_at >= df)
        except ValueError:
            pass
    if date_to:
        try:
            dt_ = dt.strptime(date_to.strip(), "%Y-%m-%d")
            # 包含当日全天
            from datetime import timedelta
            dt_end = dt_ + timedelta(days=1)
            q = q.filter(models.AuditLog.created_at < dt_end)
        except ValueError:
            pass
    total = q.count()
    q = q.order_by(models.AuditLog.created_at.desc())
    rows = q.offset(offset).limit(limit).all()
    return rows, total
