"""数据源策略路由。

根据租户 source_mode 动态选择 FeishuDataSourceStrategy 或 DBDataSourceStrategy。
"""

from __future__ import annotations

from typing import Dict

from sqlalchemy.orm import Session

from .. import models
from .base import DataSourceConfig, DataSourceStrategy, PriceItem
from .feishu_strategy import FeishuDataSourceStrategy
from .db_strategy import DBDataSourceStrategy

_feishu_strategy = FeishuDataSourceStrategy()
_db_strategy = DBDataSourceStrategy()


def _build_config(db: Session, tenant_id: int) -> DataSourceConfig:
    """从 DB 读取租户配置，组装 DataSourceConfig。"""
    import logging
    logger = logging.getLogger("datasource._build_config")

    # 强制刷新 session 缓存，确保读到最新的 DB 配置（解决切换数据源后连接未更新问题）
    db.expire_all()
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if not tenant:
        raise ValueError(f"商户 {tenant_id} 不存在")
    # 显式 refresh 确保拿到最新提交的值
    db.refresh(tenant)

    cfg = db.query(models.TenantConfig).filter(models.TenantConfig.tenant_id == tenant_id).first()
    if cfg:
        db.refresh(cfg)
    else:
        logger.warning(f"[tenant_id={tenant_id}] _build_config: no TenantConfig found for this tenant!")

    db_url = (cfg.db_url or "").strip() if cfg else ""
    db_username = (cfg.db_username or "").strip() if cfg else ""
    db_company_code = (cfg.db_company_code or "").strip() if cfg else ""
    logger.info(f"[tenant_id={tenant_id}] _build_config: source_mode={tenant.source_mode}, db_url={db_url}, db_username={db_username}, db_company_code={db_company_code}")

    return DataSourceConfig(
        tenant_code=tenant.code,
        source_mode=tenant.source_mode or "feishu",
        feishu_app_id=(cfg.feishu_app_id or "").strip() if cfg else "",
        feishu_app_secret=(cfg.feishu_app_secret or "").strip() if cfg else "",
        feishu_app_token=(cfg.feishu_app_token or "").strip() if cfg else "",
        feishu_table_id=(cfg.feishu_table_id or "").strip() if cfg else "",
        feishu_field_name=(cfg.feishu_field_name or "商品名称").strip() if cfg else "商品名称",
        feishu_price_field_name=(cfg.feishu_price_field_name or "报价").strip() if cfg else "报价",
        db_url=db_url,
        db_username=db_username,
        db_password=(cfg.db_password or "").strip() if cfg else "",
        db_company_code=db_company_code,
        price_date=(cfg.price_date or "").strip() if cfg else "",
        price_fields=cfg.price_fields if cfg and cfg.price_fields else None,
    )


def get_strategy(db: Session, tenant_id: int) -> tuple[DataSourceStrategy, DataSourceConfig]:
    """获取租户对应的数据源策略与配置。"""
    ds_cfg = _build_config(db, tenant_id)
    mode = ds_cfg.source_mode
    if mode == "db":
        return _db_strategy, ds_cfg
    return _feishu_strategy, ds_cfg


def fetch_all_items(db: Session, tenant_id: int) -> list[PriceItem]:
    """便捷方法：用租户对应的策略拉取全量数据。"""
    strategy, ds_cfg = get_strategy(db, tenant_id)
    return strategy.fetch_all(ds_cfg)


def validate_connection(db: Session, tenant_id: int) -> tuple[bool, str]:
    """便捷方法：校验租户数据源连接。"""
    strategy, ds_cfg = get_strategy(db, tenant_id)
    return strategy.validate_config(ds_cfg)
