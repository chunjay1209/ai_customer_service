"""Pydantic schemas for request/response."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------- Auth ----------
class LoginRequest(BaseModel):
    tenant_code: str = Field(..., description="公司代码")
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str
    display_name: str = ""
    tenant_code: str
    tenant_name: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)


class ResetPasswordRequest(BaseModel):
    username: str
    new_password: str = Field(..., min_length=6)


# ---------- Users ----------
class UserOut(BaseModel):
    id: int
    username: str
    display_name: str = ""
    role: str
    tenant_code: str

    class Config:
        from_attributes = True


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    display_name: str = Field(default="", max_length=64)
    password: str = Field(..., min_length=6)
    role: str = Field(default="sales")


class UpdateUserRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=2, max_length=32)
    display_name: Optional[str] = Field(None, max_length=64)
    role: Optional[str] = None


# ---------- Roles ----------
class RoleCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=32, description="角色标识（英文）")
    description: str = Field(default="", max_length=256)
    menu_permissions: Optional[List[str]] = Field(default=None, description="菜单权限列表")


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=32)
    description: Optional[str] = Field(None, max_length=256)
    menu_permissions: Optional[List[str]] = Field(default=None, description="菜单权限列表")


class RoleOut(BaseModel):
    id: int
    name: str
    description: str = ""
    menu_permissions: Optional[List[str]] = None
    user_count: int = 0


# ---------- Tenant Config ----------
class PriceFieldItem(BaseModel):
    """单个报价等级配置"""
    label: str = ""           # 显示名称，如 "价格1"
    field: str = ""           # 数据库字段名，如 "jg2"
    enabled: bool = False     # 是否启用


class TenantConfigIn(BaseModel):
    """商户系统参数（飞书 + LLM + DB 直连 + 报价等级）"""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_app_token: str = ""
    feishu_table_id: str = ""
    feishu_field_name: str = "商品名称"
    feishu_price_field_name: str = "报价"
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_model: str = "DeepSeek-V4-Flash"
    # DB 直连配置
    db_url: str = ""
    db_username: str = ""
    db_password: str = ""
    db_company_code: str = ""
    price_date: str = ""   # 报价日期，为空则取当日
    # 报价等级配置
    price_fields: Optional[List[PriceFieldItem]] = None
    # 数据源模式（feishu / db），保存 DB 配置时自动切换为 db
    source_mode: str = ""


class TenantConfigOut(BaseModel):
    feishu_app_id: str
    feishu_app_token: str
    feishu_table_id: str
    feishu_field_name: str
    feishu_price_field_name: str
    llm_provider: str
    llm_model: str
    has_app_secret: bool
    has_llm_api_key: bool
    # DB 直连配置
    db_url: str = ""
    db_username: str = ""
    db_company_code: str = ""
    has_db_password: bool = False
    # 报价等级配置
    price_fields: Optional[List[PriceFieldItem]] = None
    source_mode: str = "feishu"
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Business ----------
class PriceCheckRequest(BaseModel):
    text: str
    price_field: Optional[str] = None  # 指定报价等级字段，如 "jg2"


class PriceLineDetail(BaseModel):
    original: str
    keywords: List[str] = []
    price: Optional[str] = None
    matched_name: Optional[str] = None
    matched: bool


class PriceCheckResponse(BaseModel):
    result: str
    details: List[PriceLineDetail]
    sync_status: str = "ok"       # ok | no_config | fetch_error | empty
    sync_count: int = 0            # 本次同步拉取行数
    last_synced_at: Optional[str] = None  # 最后一次数据同步时间（ISO 格式）


class FeishuRowsResponse(BaseModel):
    columns: List[str]
    rows: List[dict]
    total: int
    page: int
    page_size: int
    sync_status: str = "ok"
    sync_count: int = 0
    last_synced_at: Optional[str] = None  # 最后一次数据同步时间（ISO 格式）


# ---------- Platform Admin: 商户 CRUD ----------
class TenantIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=2, max_length=128)
    is_active: int = Field(default=1, ge=0, le=1)
    source_mode: str = Field(default="feishu", description="数据源模式: feishu | db")
    contact: str = ""
    contact_info: str = ""


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[int] = None
    source_mode: Optional[str] = None
    contact: Optional[str] = None
    contact_info: Optional[str] = None


class TenantOut(BaseModel):
    id: int
    code: str
    name: str
    is_active: int
    source_mode: str = "feishu"
    contact: str = ""
    contact_info: str = ""
    user_count: int = 0
    feishu_configured: bool = False
    db_configured: bool = False

    model_config = {"from_attributes": True}


# ---------- Audit Log ----------
class AuditLogOut(BaseModel):
    id: int
    tenant_code: str
    username: str
    role: str
    action: str
    target: str = ""
    detail_json: str = "{}"
    ip_address: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}