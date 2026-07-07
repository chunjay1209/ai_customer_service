"""FastAPI 主入口（三级角色：platform_admin / tenant_admin / sales）。

Phase 1-4 变更：
- 商户 CRUD 支持 source_mode + db_configured
- 系统参数支持 DB 直连配置
- 新增数据源连接校验 API
- 审计日志埋点（登录/CRUD/查价/看板）
- 报价服务接入策略路由 + 本地缓存读写
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db, auto_migrate
from . import auth, models, schemas, audit, price_service
from .feishu_api import TenantFeishuClient, _split_multi_color_keywords, translate_brand_in_text, _expand_abbreviations, _is_color_keyword
from .llm_service import extract_keywords_for_tenant, extract_keywords_batch
from .datasource import validate_connection as ds_validate
from .polling import start_polling_scheduler, stop_polling_scheduler

_perf_log = logging.getLogger("perf.price_check")

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip 压缩：对 >500 字节的 JSON 响应自动压缩，减少传输体积
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.on_event("startup")
def on_startup():
    auto_migrate()
    start_polling_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    stop_polling_scheduler()


def _ensure_tenant_config(db: Session, tenant_id: int) -> models.TenantConfig:
    cfg = db.query(models.TenantConfig).filter(models.TenantConfig.tenant_id == tenant_id).first()
    if not cfg:
        cfg = models.TenantConfig(tenant_id=tenant_id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _role_name(db: Session, role_id: int) -> str:
    role = db.query(models.Role).filter(models.Role.id == role_id).first()
    return role.name if role else ""


def _build_tenant_out(db: Session, tenant: models.Tenant) -> dict:
    """统一构造 TenantOut 响应 dict。"""
    count = (
        db.query(func.count(models.User.id))
        .filter(models.User.tenant_id == tenant.id)
        .scalar()
        or 0
    )
    cfg = db.query(models.TenantConfig).filter(models.TenantConfig.tenant_id == tenant.id).first()
    feishu_ok = bool(cfg and cfg.feishu_app_id and cfg.feishu_app_secret and cfg.feishu_app_token and cfg.feishu_table_id)
    db_ok = bool(cfg and cfg.db_url and cfg.db_username and cfg.db_company_code)
    return {
        "id": tenant.id,
        "code": tenant.code,
        "name": tenant.name,
        "is_active": int(tenant.is_active or 0),
        "source_mode": tenant.source_mode or "feishu",
        "contact": tenant.contact or "",
        "contact_info": tenant.contact_info or "",
        "user_count": int(count),
        "feishu_configured": feishu_ok,
        "db_configured": db_ok,
    }


# =====================================================================
# 鉴权
# =====================================================================
@app.post("/api/auth/login", response_model=schemas.TokenResponse)
def login(req: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = auth.authenticate_user(db, req.tenant_code, req.username, req.password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    role = db.query(models.Role).filter(models.Role.id == user.role_id).first()
    tenant = db.query(models.Tenant).filter(models.Tenant.id == user.tenant_id).first()
    token = auth.create_access_token(
        {"user_id": user.id, "tenant_code": tenant.code, "role": role.name}
    )
    # 审计日志
    audit.log(db,
        tenant_code=tenant.code,
        username=user.username,
        role=role.name,
        action="login",
        ip_address=request.client.host if request.client else "",
    )
    return schemas.TokenResponse(
        access_token=token,
        role=role.name,
        username=user.username,
        display_name=user.display_name or user.username,
        tenant_code=tenant.code,
        tenant_name=tenant.name if role.name != "platform_admin" else "平台运营后台",
    )


@app.post("/api/auth/change-password")
def change_password(
    req: schemas.ChangePasswordRequest,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if not auth.verify_password(req.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码错误")
    user.password_hash = auth.hash_password(req.new_password)
    db.commit()
    return {"ok": True, "msg": "密码已更新"}


@app.get("/api/auth/me")
def me(user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    role = db.query(models.Role).filter(models.Role.id == user.role_id).first()
    tenant = db.query(models.Tenant).filter(models.Tenant.id == user.tenant_id).first()
    return {
        "id": user.id,
        "username": user.username,
        "role": role.name,
        "tenant_code": tenant.code,
        "tenant_name": tenant.name,
        "source_mode": tenant.source_mode or "feishu",
    }


# =====================================================================
# 平台运营后台：商户 CRUD + 全局报价监控
# =====================================================================
@app.get("/api/platform/tenants", response_model=List[schemas.TenantOut])
def list_tenants(
    _platform: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(models.Tenant).all()
    return [_build_tenant_out(db, t) for t in rows]


@app.post("/api/platform/tenants", response_model=schemas.TenantOut)
def create_tenant(
    req: schemas.TenantIn,
    _platform: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    exists = db.query(models.Tenant).filter(models.Tenant.code == req.code).first()
    if exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "公司代码已存在")
    tenant = models.Tenant(
        code=req.code,
        name=req.name,
        is_active=int(req.is_active),
        source_mode=req.source_mode or "feishu",
        contact=req.contact or "",
        contact_info=req.contact_info or "",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    # 自动创建默认 admin / 123456
    tenant_admin_role = db.query(models.Role).filter(models.Role.name == "tenant_admin").first()
    default_admin = models.User(
        tenant_id=tenant.id,
        role_id=tenant_admin_role.id,
        username="admin",
        password_hash=auth.hash_password("123456"),
    )
    db.add(default_admin)

    # 预先创建一条空的 TenantConfig
    db.add(models.TenantConfig(tenant_id=tenant.id))
    db.commit()
    db.refresh(tenant)

    return _build_tenant_out(db, tenant)


@app.put("/api/platform/tenants/{tenant_id}", response_model=schemas.TenantOut)
def update_tenant(
    tenant_id: int,
    req: schemas.TenantUpdate,
    _platform: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商户不存在")
    if req.name is not None:
        tenant.name = req.name
    if req.is_active is not None:
        tenant.is_active = int(req.is_active)
    if req.source_mode is not None:
        if req.source_mode not in ("feishu", "db"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_mode 仅支持 feishu 或 db")
        tenant.source_mode = req.source_mode
    if req.contact is not None:
        tenant.contact = req.contact
    if req.contact_info is not None:
        tenant.contact_info = req.contact_info
    db.commit()
    db.refresh(tenant)
    return _build_tenant_out(db, tenant)


@app.delete("/api/platform/tenants/{tenant_id}")
def delete_tenant(
    tenant_id: int,
    platform_user: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商户不存在")
    if tenant.code.lower() in ("byadmin", "platform"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除平台内部租户")
    if platform_user.tenant_id == tenant.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除当前账号所在租户")
    db.delete(tenant)
    db.commit()
    return {"ok": True}


@app.get("/api/platform/tenants/{tenant_id}/config", response_model=schemas.TenantConfigOut)
def get_tenant_config_by_platform(
    tenant_id: int,
    _platform: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    """平台管理员查看指定商户的飞书/LLM/DB配置。"""
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商户不存在")
    cfg = _ensure_tenant_config(db, tenant_id)
    return {
        "feishu_app_id": cfg.feishu_app_id or "",
        "feishu_app_token": cfg.feishu_app_token or "",
        "feishu_table_id": cfg.feishu_table_id or "",
        "feishu_field_name": cfg.feishu_field_name or "商品名称",
        "feishu_price_field_name": cfg.feishu_price_field_name or "报价",
        "llm_provider": cfg.llm_provider or "gemini",
        "llm_model": cfg.llm_model or "DeepSeek-V4-Flash",
        "has_app_secret": bool(cfg.feishu_app_secret),
        "has_llm_api_key": bool(cfg.llm_api_key),
        "db_url": cfg.db_url or "",
        "db_username": cfg.db_username or "",
        "db_company_code": cfg.db_company_code or "",
        "has_db_password": bool(cfg.db_password),
        "price_date": cfg.price_date or "",
        "price_fields": cfg.price_fields or [],
        "source_mode": tenant.source_mode or "feishu",
        "last_synced_at": cfg.last_synced_at,
    }


@app.put("/api/platform/tenants/{tenant_id}/config", response_model=schemas.TenantConfigOut)
def update_tenant_config_by_platform(
    tenant_id: int,
    req: schemas.TenantConfigIn,
    _platform: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    """平台管理员更新指定商户的飞书/LLM/DB配置。"""
    import logging
    logger = logging.getLogger("api.update_tenant_config")
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商户不存在")
    cfg = _ensure_tenant_config(db, tenant_id)

    cfg.feishu_app_id = req.feishu_app_id.strip()
    if req.feishu_app_secret.strip():
        cfg.feishu_app_secret = req.feishu_app_secret.strip()
    cfg.feishu_app_token = req.feishu_app_token.strip()
    cfg.feishu_table_id = req.feishu_table_id.strip()
    cfg.feishu_field_name = (req.feishu_field_name or "商品名称").strip()
    cfg.feishu_price_field_name = (req.feishu_price_field_name or "报价").strip()

    cfg.llm_provider = (req.llm_provider or "gemini").strip()
    if req.llm_api_key.strip():
        cfg.llm_api_key = req.llm_api_key.strip()
    cfg.llm_model = (req.llm_model or "DeepSeek-V4-Flash").strip()

    cfg.db_url = req.db_url.strip()
    cfg.db_username = req.db_username.strip()
    cfg.db_company_code = req.db_company_code.strip()
    cfg.price_date = req.price_date.strip()
    if req.db_password.strip():
        cfg.db_password = req.db_password.strip()
    if req.price_fields is not None:
        cfg.price_fields = [pf.dict() for pf in req.price_fields] if req.price_fields else []

    # 自动切换数据源模式：填写了 DB 配置 → 切换为 db 模式
    if req.source_mode.strip():
        tenant.source_mode = req.source_mode.strip()
    elif req.db_url.strip():
        tenant.source_mode = "db"

    logger.info(f"[tenant_id={tenant_id}, code={tenant.code}] update_tenant_config: source_mode={tenant.source_mode}, db_url={cfg.db_url}, db_username={cfg.db_username}, db_company_code={cfg.db_company_code}, price_date={cfg.price_date}")

    db.commit()
    db.refresh(cfg)
    db.refresh(tenant)

    # 配置变更后清除内存缓存，确保价格字段映射立即生效
    price_service._invalidate_cache(tenant.code, tenant.source_mode or "feishu")
    price_service._invalidate_cache(tenant.code, "")

    # 若价格字段配置有变化，清除 DB 缓存并触发重新同步
    # 否则前端会继续读取旧 price_cache 中的 stale price_map
    if req.price_fields is not None:
        from sqlalchemy import text as sqla_text
        db.execute(
            sqla_text("DELETE FROM price_cache WHERE tenant_code = :tc"),
            {"tc": tenant.code},
        )
        db.commit()
        price_service._trigger_async_sync(tenant.id, tenant.code)
        logger.info(f"[tenant_id={tenant_id}, code={tenant.code}] price_fields changed: DB cache cleared & async sync triggered")
    logger.info(f"[tenant_id={tenant_id}, code={tenant.code}] update_tenant_config: memory cache cleared")

    logger.info(f"[tenant_id={tenant_id}, code={tenant.code}] update_tenant_config AFTER commit: source_mode={tenant.source_mode}, db_url={cfg.db_url}")

    return {
        "feishu_app_id": cfg.feishu_app_id or "",
        "feishu_app_token": cfg.feishu_app_token or "",
        "feishu_table_id": cfg.feishu_table_id or "",
        "feishu_field_name": cfg.feishu_field_name or "商品名称",
        "feishu_price_field_name": cfg.feishu_price_field_name or "报价",
        "llm_provider": cfg.llm_provider or "gemini",
        "llm_model": cfg.llm_model or "DeepSeek-V4-Flash",
        "has_app_secret": bool(cfg.feishu_app_secret),
        "has_llm_api_key": bool(cfg.llm_api_key),
        "db_url": cfg.db_url or "",
        "db_username": cfg.db_username or "",
        "db_company_code": cfg.db_company_code or "",
        "has_db_password": bool(cfg.db_password),
        "price_date": cfg.price_date or "",
        "price_fields": cfg.price_fields or [],
        "source_mode": tenant.source_mode or "feishu",
        "last_synced_at": cfg.last_synced_at,
    }


@app.post("/api/platform/tenants/{tenant_id}/validate-db")
def validate_tenant_db(
    tenant_id: int,
    _platform: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    """平台管理员测试指定商户的数据库连接是否可用。"""
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商户不存在")
    cfg = _ensure_tenant_config(db, tenant_id)
    if not cfg.db_url or not cfg.db_username:
        return {"ok": False, "message": "数据库连接串或用户名未填写"}
    import pymysql
    from .datasource.db_strategy import _parse_db_url
    kwargs = _parse_db_url(cfg.db_url.strip(), cfg.db_username.strip(), (cfg.db_password or "").strip())
    if not kwargs:
        return {"ok": False, "message": "数据库连接串格式无法解析（支持格式: host:port/database 或 jdbc:mysql://host:port/database）"}
    try:
        conn = pymysql.connect(**kwargs)
        conn.close()
        return {"ok": True, "message": f"连接成功（{kwargs['host']}:{kwargs['port']}/{kwargs['database']}）"}
    except Exception as e:
        return {"ok": False, "message": f"连接失败: {str(e)}"}


@app.post("/api/platform/tenants/{tenant_code}/refresh-cache")
def platform_tenant_refresh_cache(
    tenant_code: str,
    _platform: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    """运营平台：强制刷新指定商户的报价缓存，重新从数据源拉取数据。"""
    result = price_service.refresh_tenant_cache(db, tenant_code)
    if not result["ok"]:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, result["message"])
    return result


@app.get("/api/platform/tenants/{tenant_code}/rows", response_model=schemas.FeishuRowsResponse)
def platform_tenant_rows(
    tenant_code: str,
    page: int = 1,
    page_size: int = 100,
    keyword: str = "",
    _platform: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    tenant = db.query(models.Tenant).filter(models.Tenant.code == tenant_code).first()
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商户不存在")
    # 使用 price_service 统一拉取（自动适配飞书/DB 直连），启用自动刷新
    cache_rows, sync_status, sync_count, _ = price_service.get_rows_from_cache(db, tenant.code, force_refresh=False, auto_refresh=True)

    # 先用 product_name 快速过滤（避免解析所有 JSON）
    kw = (keyword or "").strip().upper()
    if kw:
        filtered_rows = [r for r in cache_rows if kw in (r["product_name"] or "").upper()]
    else:
        filtered_rows = cache_rows

    total = len(filtered_rows)
    try:
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 500)
    except Exception:
        page, page_size = 1, 100
    start = (page - 1) * page_size
    paged = filtered_rows[start:start + page_size]

    # 只对当前页的数据解析 JSON（大幅提升性能）
    import json as _json

    # 读取商户报价等级配置，确定哪些价格列展示
    cfg = _ensure_tenant_config(db, tenant.id)
    price_fields_cfg = cfg.price_fields or []
    active_price_fields = [pf for pf in price_fields_cfg if pf.get("enabled")]

    # 固定列 + 动态价格列
    fixed_cols = ["商品型号", "颜色", "商品名称", "库存数量", "库存成本"]
    price_cols = [pf.get("label", f"价格{i+1}") for i, pf in enumerate(active_price_fields)]
    if not price_cols:
        price_cols = ["价格1"]
    display_cols = fixed_cols[:3] + price_cols + fixed_cols[3:]

    rows = []
    for r in paged:
        extra = {}
        try:
            extra = _json.loads(r.get("extra_json", "{}") or "{}")
        except Exception:
            extra = {}
        pm = extra.get("price_map", {})
        # 多源兜底取价格：price_map[field] → extra[field] → extra[label] → r["price"]
        def _get_price_val(field: str, label: str = "") -> str:
            val = pm.get(field, "")
            if not val:
                val = extra.get(field, "")
            if not val and label:
                val = extra.get(label, "")
            if not val:
                val = str(r.get("price", "") or "")
            return str(val).strip() if val else ""

        # 多源兜底取库存/成本
        stock_val = extra.get("库存数量", "") or extra.get("kcsl", "") or ""
        cost_val = extra.get("库存成本", "") or extra.get("kccb", "") or ""
        row = {
            "商品型号": extra.get("商品型号", "") or "",
            "颜色": extra.get("颜色", "") or "",
            "商品名称": r["product_name"] or "",
            "库存数量": str(stock_val).strip() if stock_val else "",
            "库存成本": str(cost_val).strip() if cost_val else "",
        }
        for pf in active_price_fields:
            label = pf.get("label", "")
            field = pf.get("field", "")
            if not label:
                continue
            row[label] = _get_price_val(field, label)
        if not active_price_fields:
            row["价格1"] = _get_price_val("jg4", "价格1")
        rows.append(row)

    columns = display_cols
    return {
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "sync_status": sync_status,
        "sync_count": sync_count,
        "last_synced_at": price_service.format_last_synced_utc(cfg.last_synced_at if cfg else None),
    }


@app.post("/api/platform/tenants/{tenant_code}/check-price", response_model=schemas.PriceCheckResponse)
def platform_tenant_price(
    tenant_code: str,
    req: schemas.PriceCheckRequest,
    _platform: models.User = Depends(auth.require_platform_admin),
    db: Session = Depends(get_db),
):
    tenant = db.query(models.Tenant).filter(models.Tenant.code == tenant_code).first()
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商户不存在")
    cfg = _ensure_tenant_config(db, tenant.id)

    # 确定报价等级字段
    price_field = req.price_field
    if not price_field:
        price_fields_cfg = cfg.price_fields or []
        enabled = [pf for pf in price_fields_cfg if pf.get("enabled")]
        if enabled:
            price_field = enabled[0].get("field", "")

    # 预取所有缓存行（一次 DB 查询，所有行复用）
    cache_rows, sync_status, sync_count, _ = price_service.get_rows_from_cache(
        db, tenant.code, auto_refresh=True
    )

    # 批量提取关键词（一次 LLM 调用处理所有行，或无 LLM 时本地快速提取）
    all_lines_raw = req.text.split("\n")
    all_lines = [raw.rstrip() for raw in all_lines_raw]
    non_empty_lines = [translate_brand_in_text(_expand_abbreviations(line.strip())) for line in all_lines if line.strip()]
    all_keywords = extract_keywords_batch(
        non_empty_lines, cfg
    ) if non_empty_lines else []

    # 多颜色拆分：对每行关键词检查是否包含多个颜色词，拆分为多组
    expanded_keywords: list[list[str]] = []
    expanded_to_original: list[int] = []
    for i, kws in enumerate(all_keywords):
        splits = _split_multi_color_keywords(kws)
        for split_kws in splits:
            expanded_keywords.append(split_kws)
            expanded_to_original.append(i)

    # 批量匹配（预计算归一化数据，一次遍历匹配所有行）
    batch_results = price_service.search_price_in_rows_batch(
        cache_rows,
        cfg.feishu_field_name or "商品名称",
        cfg.feishu_price_field_name or "报价",
        expanded_keywords,
        price_field=price_field,
    ) if cache_rows and expanded_keywords else []

    # 构建结果：按原始行合并
    result_idx = 0
    kw_idx = 0

    out_lines: List[str] = []
    details: List[dict] = []
    match_count = 0
    prev_empty = False

    for raw in all_lines:
        raw = raw.rstrip()
        if not raw.strip():
            if not prev_empty and out_lines:
                out_lines.append("")
                prev_empty = True
            continue
        prev_empty = False

        keywords = all_keywords[kw_idx] if kw_idx < len(all_keywords) else []
        line_matches: list[dict] = []

        while result_idx < len(expanded_to_original) and expanded_to_original[result_idx] == kw_idx:
            exp_kws = expanded_keywords[result_idx]
            price: Optional[str] = None
            matched_name: Optional[str] = None
            stock: Optional[str] = None
            if result_idx < len(batch_results):
                price, matched_name, stock = batch_results[result_idx]
            if price is not None:
                line_matches.append({
                    "keywords": exp_kws, "price": price,
                    "matched_name": matched_name, "stock": stock,
                })
            result_idx += 1

        kw_idx += 1

        if not line_matches:
            out_lines.append(raw)
            details.append({"original": raw, "keywords": keywords, "price": None, "matched_name": None, "matched": False, "stock": None})
        elif len(line_matches) == 1:
            m = line_matches[0]
            price = m["price"]
            matched_name = m["matched_name"]
            stock = m["stock"]
            if price == "0":
                out_lines.append(raw)
            else:
                out_lines.append(f"{raw}   {price}")
            match_count += 1
            details.append({"original": raw, "keywords": m["keywords"], "price": price, "matched_name": matched_name, "matched": True, "stock": stock})
        else:
            match_count += len(line_matches)
            detail_entry = {"original": raw, "keywords": keywords, "matched": True, "multi_matches": []}
            for m in line_matches:
                price = m["price"]
                matched_name = m["matched_name"]
                stock = m["stock"]
                if price == "0":
                    out_lines.append(f"{raw} [{matched_name}]")
                else:
                    out_lines.append(f"{raw} [{matched_name}]   {price}")
                detail_entry["multi_matches"].append({
                    "price": price, "matched_name": matched_name,
                    "keywords": m["keywords"], "stock": stock,
                })
            details.append(detail_entry)
    # 获取最后同步时间
    cfg_obj = db.query(models.TenantConfig).filter(models.TenantConfig.tenant_id == tenant.id).first()
    last_synced_at = price_service.format_last_synced_utc(cfg_obj.last_synced_at if cfg_obj else None)
    return {"result": "\n".join(out_lines), "details": details,
            "sync_status": sync_status, "sync_count": sync_count,
            "last_synced_at": last_synced_at}


# =====================================================================
# 商户管理员：员工管理 & 飞书/LLM/DB 系统参数
# =====================================================================
@app.get("/api/admin/users", response_model=List[schemas.UserOut])
def list_users(
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(models.User).filter(models.User.tenant_id == admin.tenant_id).all()
    tenant = db.query(models.Tenant).filter(models.Tenant.id == admin.tenant_id).first()
    out: List[dict] = []
    for u in rows:
        role = db.query(models.Role).filter(models.Role.id == u.role_id).first()
        out.append({"id": u.id, "username": u.username, "display_name": u.display_name or "", "role": role.name, "tenant_code": tenant.code})
    return out


@app.post("/api/admin/users", response_model=schemas.UserOut)
def create_user(
    req: schemas.CreateUserRequest,
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    if req.role == "platform_admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不允许创建平台管理员")
    exists = (
        db.query(models.User)
        .filter(models.User.tenant_id == admin.tenant_id, models.User.username == req.username)
        .first()
    )
    if exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该用户名已存在")
    role = db.query(models.Role).filter(models.Role.name == req.role).first()
    if not role:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "角色不存在")
    tenant = db.query(models.Tenant).filter(models.Tenant.id == admin.tenant_id).first()
    user = models.User(
        tenant_id=tenant.id,
        role_id=role.id,
        username=req.username,
        display_name=req.display_name or "",
        password_hash=auth.hash_password(req.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # 审计日志
    audit.log(db, tenant_code=tenant.code, username=admin.username,
              role=_role_name(db, admin.role_id), action="user_create",
              target=req.username, detail={"role": req.role})
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or "",
        "role": role.name,
        "tenant_code": tenant.code,
    }


@app.put("/api/admin/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    req: schemas.UpdateUserRequest,
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    user = (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.tenant_id == admin.tenant_id)
        .first()
    )
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if req.username is not None and req.username != user.username:
        exists = (
            db.query(models.User)
            .filter(models.User.tenant_id == admin.tenant_id, models.User.username == req.username)
            .first()
        )
        if exists:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "该用户名已存在")
        user.username = req.username
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.role is not None:
        role = db.query(models.Role).filter(models.Role.name == req.role).first()
        if not role:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "角色不存在")
        if req.role == "platform_admin":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能将员工设为平台管理员")
        user.role_id = role.id
    db.commit()
    db.refresh(user)
    tenant = db.query(models.Tenant).filter(models.Tenant.id == admin.tenant_id).first()
    role = db.query(models.Role).filter(models.Role.id == user.role_id).first()
    # 审计日志
    audit.log(db, tenant_code=tenant.code, username=admin.username,
              role=_role_name(db, admin.role_id), action="user_update",
              target=user.username, detail={"new_role": role.name})
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or "",
        "role": role.name,
        "tenant_code": tenant.code,
    }


@app.post("/api/admin/users/reset-password")
def reset_password(
    req: schemas.ResetPasswordRequest,
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    user = (
        db.query(models.User)
        .filter(
            models.User.tenant_id == admin.tenant_id,
            models.User.username == req.username,
        )
        .first()
    )
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    user.password_hash = auth.hash_password(req.new_password)
    db.commit()
    return {"ok": True, "msg": "密码已重置"}


@app.delete("/api/admin/users/{user_id}")
def delete_user(
    user_id: int,
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    user = (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.tenant_id == admin.tenant_id)
        .first()
    )
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")
    # 审计日志（在删除前记录）
    tenant = db.query(models.Tenant).filter(models.Tenant.id == admin.tenant_id).first()
    audit.log(db, tenant_code=tenant.code, username=admin.username,
              role=_role_name(db, admin.role_id), action="user_delete",
              target=user.username)
    db.delete(user)
    db.commit()
    return {"ok": True}


# =====================================================================
# 角色管理 CRUD（商户管理员可用）
# =====================================================================
BUILTIN_ROLES = {"platform_admin", "tenant_admin", "sales"}


@app.get("/api/admin/roles", response_model=List[schemas.RoleOut])
def list_roles(
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(models.Role).all()
    out: List[dict] = []
    for r in rows:
        count = (
            db.query(func.count(models.User.id))
            .filter(models.User.role_id == r.id)
            .scalar()
            or 0
        )
        out.append({
            "id": r.id,
            "name": r.name,
            "description": r.description or "",
            "menu_permissions": r.menu_permissions or [],
            "user_count": int(count),
        })
    return out


@app.post("/api/admin/roles", response_model=schemas.RoleOut)
def create_role(
    req: schemas.RoleCreate,
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    exists = db.query(models.Role).filter(models.Role.name == req.name).first()
    if exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "角色标识已存在")
    role = models.Role(name=req.name, description=req.description or "", menu_permissions=req.menu_permissions or [])
    db.add(role)
    db.commit()
    db.refresh(role)
    # 审计日志
    tenant = db.query(models.Tenant).filter(models.Tenant.id == admin.tenant_id).first()
    audit.log(db, tenant_code=tenant.code, username=admin.username,
              role=_role_name(db, admin.role_id), action="role_create",
              target=req.name)
    return {"id": role.id, "name": role.name, "description": role.description or "", "menu_permissions": role.menu_permissions or [], "user_count": 0}


@app.put("/api/admin/roles/{role_id}", response_model=schemas.RoleOut)
def update_role(
    role_id: int,
    req: schemas.RoleUpdate,
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    role = db.query(models.Role).filter(models.Role.id == role_id).first()
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "角色不存在")
    if req.name is not None and req.name != role.name:
        if role.name in BUILTIN_ROLES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"内置角色「{role.name}」不允许改名")
        exists = db.query(models.Role).filter(models.Role.name == req.name).first()
        if exists:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "角色标识已存在")
        role.name = req.name
    if req.description is not None:
        role.description = req.description
    if req.menu_permissions is not None:
        role.menu_permissions = req.menu_permissions
    db.commit()
    db.refresh(role)
    count = (
        db.query(func.count(models.User.id))
        .filter(models.User.role_id == role.id)
        .scalar()
        or 0
    )
    return {"id": role.id, "name": role.name, "description": role.description or "", "menu_permissions": role.menu_permissions or [], "user_count": int(count)}


@app.delete("/api/admin/roles/{role_id}")
def delete_role(
    role_id: int,
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    role = db.query(models.Role).filter(models.Role.id == role_id).first()
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "角色不存在")
    if role.name in BUILTIN_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"内置角色「{role.name}」不允许删除")
    count = (
        db.query(func.count(models.User.id))
        .filter(models.User.role_id == role.id)
        .scalar()
        or 0
    )
    if count > 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"该角色下还有 {count} 个用户，无法删除")
    db.delete(role)
    db.commit()
    return {"ok": True}


# =====================================================================
# 审计日志查询（Phase 4 新增）
# =====================================================================
@app.get("/api/admin/audit-logs")
def get_audit_logs(
    action: str = "",
    username: str = "",
    tenant_code: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    page_size: int = 100,
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    """查询审计日志（支持分页）。platform_admin 可通过 tenant_code 指定商户。"""
    role = _role_name(db, admin.role_id)
    if role == "platform_admin":
        tc = tenant_code.strip()
    else:
        tenant = db.query(models.Tenant).filter(models.Tenant.id == admin.tenant_id).first()
        tc = tenant.code if tenant else ""
    page = max(page, 1)
    page_size = min(max(page_size, 10), 100)
    offset = (page - 1) * page_size
    rows, total = audit.get_logs(
        db, tenant_code=tc, action=action, username=username,
        date_from=date_from, date_to=date_to,
        limit=page_size, offset=offset,
    )
    return {
        "items": [
            {
                "id": r.id,
                "tenant_code": r.tenant_code,
                "username": r.username,
                "role": r.role,
                "action": r.action,
                "target": r.target or "",
                "detail_json": r.detail_json or "{}",
                "ip_address": r.ip_address or "",
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# =====================================================================
# 系统参数（飞书 + LLM + DB 直连）
# =====================================================================
@app.get("/api/admin/config", response_model=schemas.TenantConfigOut)
def get_config(
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    cfg = _ensure_tenant_config(db, admin.tenant_id)
    tenant = db.query(models.Tenant).filter(models.Tenant.id == admin.tenant_id).first()
    return {
        "feishu_app_id": cfg.feishu_app_id or "",
        "feishu_app_token": cfg.feishu_app_token or "",
        "feishu_table_id": cfg.feishu_table_id or "",
        "feishu_field_name": cfg.feishu_field_name or "商品名称",
        "feishu_price_field_name": cfg.feishu_price_field_name or "报价",
        "llm_provider": cfg.llm_provider or "gemini",
        "llm_model": cfg.llm_model or "DeepSeek-V4-Flash",
        "has_app_secret": bool(cfg.feishu_app_secret),
        "has_llm_api_key": bool(cfg.llm_api_key),
        "db_url": cfg.db_url or "",
        "db_username": cfg.db_username or "",
        "db_company_code": cfg.db_company_code or "",
        "has_db_password": bool(cfg.db_password),
        "price_date": cfg.price_date or "",
        "price_fields": cfg.price_fields or [],
        "source_mode": tenant.source_mode if tenant else "feishu",
        "last_synced_at": cfg.last_synced_at,
    }


@app.put("/api/admin/config", response_model=schemas.TenantConfigOut)
def update_config(
    req: schemas.TenantConfigIn,
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    cfg = _ensure_tenant_config(db, admin.tenant_id)
    tenant = db.query(models.Tenant).filter(models.Tenant.id == admin.tenant_id).first()

    # 飞书配置
    cfg.feishu_app_id = req.feishu_app_id.strip()
    if req.feishu_app_secret.strip():
        cfg.feishu_app_secret = req.feishu_app_secret.strip()
    cfg.feishu_app_token = req.feishu_app_token.strip()
    cfg.feishu_table_id = req.feishu_table_id.strip()
    cfg.feishu_field_name = (req.feishu_field_name or "商品名称").strip()
    cfg.feishu_price_field_name = (req.feishu_price_field_name or "报价").strip()

    # LLM 配置
    cfg.llm_provider = (req.llm_provider or "gemini").strip()
    if req.llm_api_key.strip():
        cfg.llm_api_key = req.llm_api_key.strip()
    cfg.llm_model = (req.llm_model or "DeepSeek-V4-Flash").strip()

    # DB 直连配置（新增）
    cfg.db_url = req.db_url.strip()
    cfg.db_username = req.db_username.strip()
    cfg.db_company_code = req.db_company_code.strip()
    cfg.price_date = req.price_date.strip()
    if req.db_password.strip():
        cfg.db_password = req.db_password.strip()
    if req.price_fields is not None:
        cfg.price_fields = [pf.dict() for pf in req.price_fields] if req.price_fields else []

    # 自动切换数据源模式：填写了 DB 配置 → 切换为 db 模式
    if req.source_mode.strip():
        tenant.source_mode = req.source_mode.strip()
    elif req.db_url.strip():
        tenant.source_mode = "db"

    db.commit()
    db.refresh(cfg)

    # 若价格字段配置有变化，清除 DB 缓存并触发重新同步
    if req.price_fields is not None:
        from sqlalchemy import text as sqla_text
        db.execute(
            sqla_text("DELETE FROM price_cache WHERE tenant_code = :tc"),
            {"tc": tenant.code},
        )
        db.commit()
        price_service._invalidate_cache(tenant.code, tenant.source_mode or "feishu")
        price_service._invalidate_cache(tenant.code, "")
        price_service._trigger_async_sync(tenant.id, tenant.code)
        logger.info(f"[admin, tenant_id={tenant.id}, code={tenant.code}] price_fields changed: DB cache cleared & async sync triggered")

    return {
        "feishu_app_id": cfg.feishu_app_id or "",
        "feishu_app_token": cfg.feishu_app_token or "",
        "feishu_table_id": cfg.feishu_table_id or "",
        "feishu_field_name": cfg.feishu_field_name or "商品名称",
        "feishu_price_field_name": cfg.feishu_price_field_name or "报价",
        "llm_provider": cfg.llm_provider or "gemini",
        "llm_model": cfg.llm_model or "DeepSeek-V4-Flash",
        "has_app_secret": bool(cfg.feishu_app_secret),
        "has_llm_api_key": bool(cfg.llm_api_key),
        "db_url": cfg.db_url or "",
        "db_username": cfg.db_username or "",
        "db_company_code": cfg.db_company_code or "",
        "has_db_password": bool(cfg.db_password),
        "price_date": cfg.price_date or "",
        "price_fields": cfg.price_fields or [],
        "source_mode": tenant.source_mode,
        "last_synced_at": cfg.last_synced_at,
    }


# =====================================================================
# 数据源连接校验（新增）
# =====================================================================
@app.get("/api/admin/config/validate")
def validate_data_source(
    admin: models.User = Depends(auth.require_tenant_admin),
    db: Session = Depends(get_db),
):
    """校验当前商户数据源连接是否可用。"""
    ok, msg = ds_validate(db, admin.tenant_id)
    return {"ok": ok, "message": msg}


# =====================================================================
# 报价看板 & AI 查价（业务员 + 商户管理员）
# =====================================================================

def _filter_by_price1(rows: list, mode: str) -> list:
    """按价格1（jg4）筛选：gt0=大于0, eq0=等于0"""
    import json as _json
    result = []
    for r in rows:
        try:
            extra = _json.loads(r.get("extra_json", "{}") or "{}")
        except Exception:
            extra = {}
        pm = extra.get("price_map", {})
        val = pm.get("jg4", "")
        if not val:
            # 回退到 price 字段
            val = str(r.get("price", "") or "")
        num = _safe_float(val)
        if mode == "gt0" and num > 0:
            result.append(r)
        elif mode == "eq0" and num == 0:
            result.append(r)
    return result


def _filter_by_stock(rows: list, mode: str) -> list:
    """按库存数量筛选：gt0=大于0, eq0=等于0"""
    import json as _json
    result = []
    for r in rows:
        try:
            extra = _json.loads(r.get("extra_json", "{}") or "{}")
        except Exception:
            extra = {}
        val = str(extra.get("库存数量", "") or "")
        num = _safe_float(val)
        if mode == "gt0" and num > 0:
            result.append(r)
        elif mode == "eq0" and num == 0:
            result.append(r)
    return result


def _safe_float(val: str) -> float:
    """安全转 float，失败返回 0"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0


@app.get("/api/feishu/rows", response_model=schemas.FeishuRowsResponse)
def feishu_rows(
    refresh: bool = False,
    page: int = 1,
    page_size: int = 100,
    keyword: str = "",
    price1_filter: str = "gt0",  # gt0: 大于0, eq0: 等于0, all: 全部
    stock_filter: str = "all",   # gt0: 大于0, eq0: 等于0, all: 全部
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    import logging
    import time
    logger = logging.getLogger("api.feishu_rows")
    t0 = time.time()

    role = _role_name(db, user.role_id)
    if role == "platform_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请使用商户账号登录以查看报价")
    tenant = db.query(models.Tenant).filter(models.Tenant.id == user.tenant_id).first()

    # 通过策略路由拉取数据（自动根据 source_mode 选择飞书/DB直连），启用自动刷新
    t_cache = time.time()
    cache_rows, sync_status, sync_count, _ = price_service.get_rows_from_cache(db, tenant.code, force_refresh=bool(refresh), auto_refresh=True)
    logger.info(f"[PERF] feishu_rows({tenant.code}): get_rows_from_cache={time.time()-t_cache:.3f}s, rows={sync_count}, status={sync_status}")

    # 审计日志
    audit.log(db, tenant_code=tenant.code, username=user.username,
              role=role, action="dashboard_view",
              target=f"page={page}&refresh={refresh}")

    # 先用 product_name 快速过滤（避免解析所有 JSON）
    t_filter = time.time()
    kw = (keyword or "").strip().upper()
    if kw:
        filtered_rows = [r for r in cache_rows if kw in (r["product_name"] or "").upper()]
    else:
        filtered_rows = cache_rows

    logger.info(f"[PERF] feishu_rows({tenant.code}): keyword_filter={time.time()-t_filter:.3f}s, filtered={len(filtered_rows)}")

    # 价格1 筛选（默认大于0，隐藏报价为0的商品）
    if price1_filter != "all":
        price1_f = time.time()
        filtered_rows = _filter_by_price1(filtered_rows, price1_filter)
        logger.info(f"[PERF] feishu_rows({tenant.code}): price1_filter={time.time()-price1_f:.3f}s, filtered={len(filtered_rows)}")

    # 库存数量筛选
    if stock_filter != "all":
        stock_f = time.time()
        filtered_rows = _filter_by_stock(filtered_rows, stock_filter)
        logger.info(f"[PERF] feishu_rows({tenant.code}): stock_filter={time.time()-stock_f:.3f}s, filtered={len(filtered_rows)}")

    total = len(filtered_rows)
    try:
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 500)
    except Exception:
        page, page_size = 1, 100
    start = (page - 1) * page_size
    paged = filtered_rows[start:start + page_size]

    # 只对当前页的数据解析 JSON（大幅提升性能，避免全量解析）
    import json as _json
    t_json = time.time()

    # 读取商户报价等级配置，确定哪些价格列展示
    cfg = _ensure_tenant_config(db, user.tenant_id)
    price_fields_cfg = cfg.price_fields or []
    active_price_fields = [pf for pf in price_fields_cfg if pf.get("enabled")]

    # 固定列 + 动态价格列（按配置顺序）
    fixed_cols = ["商品型号", "颜色", "商品名称", "库存数量", "库存成本"]
    price_cols = [pf.get("label", f"价格{i+1}") for i, pf in enumerate(active_price_fields)]
    if not price_cols:
        price_cols = ["价格1"]  # 默认至少展示一个价格列
    display_cols = fixed_cols[:3] + price_cols + fixed_cols[3:]  # 商品型号, 颜色, 商品名称, [价格列...], 库存数量, 库存成本

    rows = []
    for r in paged:
        extra = {}
        try:
            extra = _json.loads(r.get("extra_json", "{}") or "{}")
        except Exception:
            extra = {}
        # 从 price_map 中取各报价等级的值（兼容 DB 直连和飞书模式）
        pm = extra.get("price_map", {})
        # 多源兜底取价格：price_map[field] → extra[field] → extra[label] → r["price"]
        def _get_price_val(field: str, label: str = "") -> str:
            val = pm.get(field, "")
            if not val:
                val = extra.get(field, "")
            if not val and label:
                val = extra.get(label, "")
            if not val:
                val = str(r.get("price", "") or "")
            return str(val).strip() if val else ""

        # 多源兜底取库存/成本
        stock_val = extra.get("库存数量", "") or extra.get("kcsl", "") or ""
        cost_val = extra.get("库存成本", "") or extra.get("kccb", "") or ""
        row = {
            "商品型号": extra.get("商品型号", "") or "",
            "颜色": extra.get("颜色", "") or "",
            "商品名称": r["product_name"] or "",
            "库存数量": str(stock_val).strip() if stock_val else "",
            "库存成本": str(cost_val).strip() if cost_val else "",
        }
        # 动态价格列：按配置的 field 取价，多源兜底
        for pf in active_price_fields:
            label = pf.get("label", "")
            field = pf.get("field", "")
            if not label:
                continue
            row[label] = _get_price_val(field, label)
        # 填充默认价格列（无配置时）：优先 jg4，其次 price 列
        if not active_price_fields:
            row["价格1"] = _get_price_val("jg4", "价格1")
        rows.append(row)

    columns = display_cols
    logger.info(f"[PERF] feishu_rows({tenant.code}): json_parse={time.time()-t_json:.3f}s, page_rows={len(rows)}, total={time.time()-t0:.3f}s")

    # 获取 last_synced_at - 强制刷新 session 以获取最新值
    db.expire_all()
    cfg = db.query(models.TenantConfig).filter(models.TenantConfig.tenant_id == user.tenant_id).first()
    last_synced_at = price_service.format_last_synced_utc(cfg.last_synced_at if cfg else None)

    return {
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "sync_status": sync_status,
        "sync_count": sync_count,
        "last_synced_at": last_synced_at,
    }


@app.post("/api/price/check", response_model=schemas.PriceCheckResponse)
def price_check(
    req: schemas.PriceCheckRequest,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    t_start = time.time()
    cfg = _ensure_tenant_config(db, user.tenant_id)
    tenant = db.query(models.Tenant).filter(models.Tenant.id == user.tenant_id).first()
    role = _role_name(db, user.role_id)

    # 确定报价等级字段
    price_field = req.price_field
    if not price_field:
        price_fields_cfg = cfg.price_fields or []
        enabled = [pf for pf in price_fields_cfg if pf.get("enabled")]
        if enabled:
            price_field = enabled[0].get("field", "")

    # 预处理输入行（纯内存，极快）
    all_lines_raw = req.text.split("\n")
    all_lines = [raw.rstrip() for raw in all_lines_raw]
    non_empty_lines = [translate_brand_in_text(_expand_abbreviations(line.strip())) for line in all_lines if line.strip()]

    # ========== 并行化：LLM 关键词提取 + DB 缓存加载 ==========
    # 两者互不依赖，并行执行可显著减少总耗时（尤其是 LLM 慢时）
    all_keywords: list[list[str]] = []
    cache_rows: list[dict] = []
    sync_status = "ok"
    sync_count = 0

    with ThreadPoolExecutor(max_workers=2) as executor:
        # 提交 LLM 关键词提取任务
        llm_future = executor.submit(
            extract_keywords_batch, non_empty_lines, cfg
        ) if non_empty_lines else None

        # DB 缓存加载：使用 auto_refresh（首次/过期自动同步），不强制刷新
        # force=False 避免每次请求都全量同步外部 DB（之前为 True，耗时 30-50s）
        db_future = executor.submit(
            price_service.get_rows_from_cache, db, tenant.code, False, True
        )

        # 等待两个任务完成
        if llm_future:
            all_keywords = llm_future.result()
        cache_rows, sync_status, sync_count, auto_refreshed = db_future.result()

    # 并行线程可能已执行 sync_from_source 并提交了事务，
    # 需要 expire_all 确保主线程读到最新数据（含更新后的 last_synced_at）
    db.expire_all()

    t_parallel = time.time()
    _perf_log.info(f"[PERF] parallel LLM+DB took {t_parallel - t_start:.3f}s")

    # 判断每行输入是否有颜色关键词
    has_color_flags = [price_service._has_color_keyword(kws) for kws in all_keywords]

    # 构建批量匹配关键词列表
    # - 有颜色输入：多颜色拆分（如 "浮光" 和 "粉" 拆为两组）
    # - 无颜色输入：原样加入（不拆分，正常匹配）
    batch_keywords: list[list[str]] = []
    batch_orig: list[int] = []

    _field_name = cfg.feishu_field_name or "商品名称"
    _price_field_name = cfg.feishu_price_field_name or "报价"

    for i, kws in enumerate(all_keywords):
        if has_color_flags[i]:
            splits = _split_multi_color_keywords(kws)
            for split_kws in splits:
                batch_keywords.append(split_kws)
                batch_orig.append(i)
        else:
            # 无颜色输入：原样加入，不做拆分
            batch_keywords.append(kws)
            batch_orig.append(i)

    # 批量匹配（所有关键词组）
    t_match = time.time()
    batch_results = price_service.search_price_in_rows_batch(
        cache_rows, _field_name, _price_field_name,
        batch_keywords, price_field=price_field,
    ) if cache_rows and batch_keywords else []
    _perf_log.info(f"[PERF] batch matching took {time.time() - t_match:.3f}s")

    # 构建结果：按原始行合并
    out_lines: List[str] = []
    details: List[dict] = []
    match_count = 0
    prev_empty = False
    batch_idx = 0   # 遍历 batch_results 的指针
    kw_idx = 0

    for raw in all_lines:
        raw = raw.rstrip()
        if not raw.strip():
            if not prev_empty and out_lines:
                out_lines.append("")
                prev_empty = True
            continue
        prev_empty = False

        keywords = all_keywords[kw_idx] if kw_idx < len(all_keywords) else []

        # === 收集该原始行对应的所有扩展匹配结果 ===
        line_matches: list[dict] = []
        while batch_idx < len(batch_orig) and batch_orig[batch_idx] == kw_idx:
            exp_kws = batch_keywords[batch_idx]
            price: Optional[str] = None
            matched_name: Optional[str] = None
            stock: Optional[str] = None
            if batch_idx < len(batch_results):
                price, matched_name, stock = batch_results[batch_idx]
            if price is not None:
                line_matches.append({
                    "keywords": exp_kws,
                    "price": price,
                    "matched_name": matched_name,
                    "stock": stock,
                })
            batch_idx += 1

        has_color = has_color_flags[kw_idx] if kw_idx < len(has_color_flags) else False

        if not line_matches:
            # 无匹配：保持原有行为
            out_lines.append(raw)
            details.append({
                "original": raw,
                "keywords": keywords,
                "price": None,
                "matched": False,
                "matched_name": None,
                "stock": None,
            })
        elif has_color and len(line_matches) >= 2:
            # 多颜色输出：单行格式"商品 颜色1 价格1 /颜色2 价格2"
            match_count += len(line_matches)
            color_parts: list[str] = []
            detail_entry = {
                "original": raw,
                "keywords": keywords,
                "matched": True,
                "multi_matches": [],
            }
            for m in line_matches:
                color_kw = next((k for k in m["keywords"] if _is_color_keyword(k)), "")
                price = m["price"]
                stock = m["stock"]
                if price == "0":
                    color_parts.append(f"{color_kw}")
                else:
                    color_parts.append(f"{color_kw} {price}")
                detail_entry["multi_matches"].append({
                    "price": price,
                    "matched_name": m["matched_name"],
                    "keywords": m["keywords"],
                    "stock": stock,
                })
            out_lines.append(f"{raw}  {' /'.join(color_parts)}")
            # 详情表：多颜色时只取第一个匹配
            first = line_matches[0]
            detail_entry["price"] = first["price"]
            detail_entry["matched_name"] = first["matched_name"]
            detail_entry["keywords"] = first["keywords"]
            detail_entry["stock"] = first["stock"]
            details.append(detail_entry)
        else:
            # 单颜色/无颜色匹配：保持原有格式（一行输出一个结果）
            m = line_matches[0]
            price = m["price"]
            matched_name = m["matched_name"]
            stock = m["stock"]
            if price == "0":
                out_lines.append(raw)
            else:
                out_lines.append(f"{raw}   {price}")
            match_count += 1
            details.append({
                "original": raw,
                "keywords": m["keywords"],
                "price": price,
                "matched": True,
                "matched_name": matched_name,
                "stock": stock,
            })
        kw_idx += 1

    # 审计日志
    audit.log(db, tenant_code=tenant.code, username=user.username,
              role=role, action="price_check",
              target=(req.text or "")[:200],
              detail={"lines": len(details), "matched": match_count})

    # 获取最后同步时间
    cfg_obj = db.query(models.TenantConfig).filter(models.TenantConfig.tenant_id == user.tenant_id).first()
    last_synced_at = price_service.format_last_synced_utc(cfg_obj.last_synced_at if cfg_obj else None)

    t_total = time.time()
    _perf_log.info(f"[PERF] price_check total: {t_total - t_start:.3f}s, lines={len(details)}, matched={match_count}")

    # 构建耗时统计（供前端展示全链路耗时分布）
    timing = {
        "parallel_llm_db_s": round(t_parallel - t_start, 2),       # LLM调用 + DB缓存加载（并行）
        "batch_matching_s": round(t_total - t_match, 3),           # 关键词批量匹配（CPU）
        "total_s": round(t_total - t_start, 2),                    # 总体耗时
        "row_count": len(cache_rows),                              # 匹配数据集大小
        "line_count": len(details),                                # 输入行数
        "matched_count": match_count,                              # 命中数
    }
    return {"result": "\n".join(out_lines), "details": details,
            "sync_status": sync_status, "sync_count": sync_count,
            "last_synced_at": last_synced_at, "timing": timing}


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "version": "2.0.0"}
