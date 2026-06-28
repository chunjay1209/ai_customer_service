"""数据库表定义。

Phase 1 增量变更：
- Tenant 新增 source_mode（数据源模式）
- TenantConfig 新增 DB 直连字段 + last_synced_at + price_fields
- 新增 PriceCache（本地报价缓存表）
- 新增 AuditLog（审计操作日志表）
- 新增 TenantActivity（商户活跃状态表）

Phase 2 增量变更：
- User 新增 display_name（显示姓名）
- Role 新增 menu_permissions（菜单权限 JSON）
- TenantConfig 新增 price_fields（报价等级配置 JSON）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from .database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=True, default="未命名公司")
    is_active = Column(Integer, nullable=False, default=1)  # 1=启用 0=停用
    source_mode = Column(String(16), nullable=False, default="feishu")  # feishu | db
    contact = Column(String(128), nullable=True, default="")      # 联系人
    contact_info = Column(String(128), nullable=True, default="") # 联系方式
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    config = relationship("TenantConfig", back_populates="tenant", uselist=False, cascade="all, delete-orphan")


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(32), unique=True, nullable=False)        # platform_admin / tenant_admin / sales
    description = Column(String(128), nullable=True)
    menu_permissions = Column(JSON, default=None, nullable=True)   # ["dashboard","price_check","users","roles","config","audit"]

    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uix_tenant_username"),)

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    username = Column(String(64), nullable=False, index=True)
    display_name = Column(String(64), default="", nullable=True)  # 显示姓名
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="users")
    role = relationship("Role", back_populates="users")


class TenantConfig(Base):
    """按租户动态存储的飞书 / LLM / DB 直连参数。"""

    __tablename__ = "tenant_configs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), unique=True, nullable=False)

    # -------- 飞书配置 --------
    feishu_app_id = Column(String(128), default="", nullable=True)
    feishu_app_secret = Column(String(255), default="", nullable=True)
    feishu_app_token = Column(String(128), default="", nullable=True)
    feishu_table_id = Column(String(128), default="", nullable=True)
    feishu_field_name = Column(String(64), default="商品名称", nullable=True)
    feishu_price_field_name = Column(String(64), default="报价", nullable=True)

    # -------- DB 直连配置 --------
    db_url = Column(String(512), default="", nullable=True)
    db_username = Column(String(128), default="", nullable=True)
    db_password = Column(String(512), default="", nullable=True)
    db_company_code = Column(String(64), default="", nullable=True)
    price_date = Column(String(16), default="", nullable=True)  # 报价日期，为空则取当日

    # -------- 报价等级配置 --------
    # JSON: [{"label":"价格1","field":"jg2","enabled":true}, {"label":"价格2","field":"jg4","enabled":true}, ...]
    price_fields = Column(JSON, default=None, nullable=True)

    # -------- LLM 配置 --------
    llm_provider = Column(String(32), default="gemini", nullable=True)
    llm_api_key = Column(String(512), default="", nullable=True)
    llm_model = Column(String(64), default="DeepSeek-V4-Flash", nullable=True)

    # -------- 同步状态 --------
    last_synced_at = Column(DateTime, default=None, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="config")


# ================================================================
# Phase 1 新增表
# ================================================================

class PriceCache(Base):
    """本地报价数据缓存表 — 统一存储飞书/DB 直连两种数据源。"""

    __tablename__ = "price_cache"
    __table_args__ = (
        UniqueConstraint("tenant_code", "source_id", "data_source", name="uix_tenant_source"),
        Index("idx_tenant_product", "tenant_code", "product_name"),
        Index("idx_tenant_sync", "tenant_code", "synced_at"),
        Index("idx_tenant_source", "tenant_code", "data_source"),  # 加速按商户+数据源查全量表
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_code = Column(String(64), nullable=False, index=True)
    source_id = Column(String(256), nullable=False)               # 原始数据源行 ID
    data_source = Column(String(16), nullable=False, default="feishu")  # feishu | db
    product_name = Column(String(512), nullable=False)
    price = Column(String(128), nullable=False)
    extra_json = Column(Text, default="{}")                       # 其它字段 JSON
    synced_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    """审计操作日志表 — 记录所有关键操作。"""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_tenant_action", "tenant_code", "action", "created_at"),
        Index("idx_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_code = Column(String(64), nullable=False, default="")
    username = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)
    action = Column(String(64), nullable=False)                   # login | logout | price_check | dashboard_view | user_create | user_update | user_delete | role_create | role_update | role_delete
    target = Column(String(256), default="")                      # 操作对象（用户名/角色名/查询文本片段）
    detail_json = Column(Text, default="{}")                      # 扩展详情
    ip_address = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TenantActivity(Base):
    """商户活跃状态表 — 用于动态轮询判断。"""

    __tablename__ = "tenant_activity"

    id = Column(Integer, primary_key=True, index=True)
    tenant_code = Column(String(64), nullable=False, unique=True, index=True)
    last_active_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    active_users = Column(Integer, default=0)
    polling = Column(Integer, default=0)                          # 是否正在轮询
