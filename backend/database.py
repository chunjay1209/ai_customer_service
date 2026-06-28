"""SQLAlchemy 引擎与会话管理。

Phase 1 变更：
- MySQL 模式下自动设置 pool_recycle（防止长连接断开）
- 添加 auto_migrate() 函数：启动时自动检测并修复缺失的数据库列（兼容旧版 SQLite schema）
"""

from __future__ import annotations

import logging
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

logger = logging.getLogger("database")

# 确保 data 目录存在（SQLite 模式）
if settings.db_url.startswith("sqlite:///"):
    raw = settings.db_url.replace("sqlite:///", "")
    if raw:
        Path(raw).parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}

engine_kwargs: dict = {
    "echo": False,
    "future": True,
    "connect_args": connect_args,
}

# MySQL 模式下自动回收连接（避免 8 小时超时断开）
if "mysql" in settings.db_url or "pymysql" in settings.db_url:
    engine_kwargs["pool_recycle"] = 3600
    engine_kwargs["pool_pre_ping"] = True

engine = create_engine(settings.db_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def auto_migrate():
    """自动检测并修复数据库 schema 中缺失的列。

    背景：SQLAlchemy 的 create_all() 只创建新表，不会为已存在的表添加新列。
    当代码迭代新增字段后，旧数据库不会自动获得新列，导致运行时报错或数据丢失。

    本函数在每次服务启动时运行，幂等安全（列已存在则跳过）。
    """
    from sqlalchemy import inspect as sa_inspect
    from datetime import datetime, timezone, timedelta

    inspector = sa_inspect(engine)

    # ── tenants 表：source_mode ──
    if "tenants" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("tenants")}
        if "source_mode" not in cols:
            logger.warning("tenants 表缺少 source_mode 列，正在修复...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN source_mode VARCHAR(16) NOT NULL DEFAULT 'feishu'"))
                conn.commit()
            logger.info("tenants.source_mode 列已添加")

    # ── tenant_configs 表：DB 直连字段 ──
    if "tenant_configs" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("tenant_configs")}
        missing_config_cols = [
            ("db_url", "VARCHAR(512) NOT NULL DEFAULT ''"),
            ("db_username", "VARCHAR(128) NOT NULL DEFAULT ''"),
            ("db_password", "VARCHAR(512) NOT NULL DEFAULT ''"),
            ("db_company_code", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("price_date", "VARCHAR(16) NOT NULL DEFAULT ''"),
            ("price_fields", "JSON"),
            ("last_synced_at", "DATETIME"),
        ]
        with engine.connect() as conn:
            for col_name, col_def in missing_config_cols:
                if col_name not in cols:
                    logger.warning(f"tenant_configs 表缺少 {col_name} 列，正在修复...")
                    conn.execute(text(f"ALTER TABLE tenant_configs ADD COLUMN {col_name} {col_def}"))
                    conn.commit()
                    logger.info(f"tenant_configs.{col_name} 列已添加")

        # ── 迁移 last_synced_at 从 UTC 到本地时间（UTC+8）──
        # 检查是否有旧数据需要迁移（假设 2026-06-20 之前的数据是 UTC 时间）
        try:
            with engine.connect() as conn:
                # 查询所有 last_synced_at 不为空且早于 2026-06-20 的记录
                result = conn.execute(text(
                    "SELECT id, last_synced_at FROM tenant_configs "
                    "WHERE last_synced_at IS NOT NULL AND last_synced_at < '2026-06-20 00:00:00'"
                ))
                rows_to_migrate = result.fetchall()
                
                if rows_to_migrate:
                    logger.warning(f"发现 {len(rows_to_migrate)} 条旧的 UTC 时间数据，正在迁移到本地时间（UTC+8）...")
                    cst = timezone(timedelta(hours=8))
                    for row_id, last_synced in rows_to_migrate:
                        # 假设旧时间是 UTC，转换为 UTC+8
                        if last_synced.tzinfo is None:
                            last_synced_utc = last_synced.replace(tzinfo=timezone.utc)
                            last_synced_local = last_synced_utc.astimezone(cst).replace(tzinfo=None)
                            conn.execute(
                                text("UPDATE tenant_configs SET last_synced_at = :new_time WHERE id = :id"),
                                {"new_time": last_synced_local, "id": row_id}
                            )
                            logger.info(f"迁移 tenant_config id={row_id}: {last_synced} (UTC) -> {last_synced_local} (UTC+8)")
                    conn.commit()
                    logger.info("last_synced_at 时间迁移完成")
        except Exception as e:
            logger.error(f"迁移 last_synced_at 时出错: {e}")

    # ── users 表：display_name ──
    if "users" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "display_name" not in cols:
            logger.warning("users 表缺少 display_name 列，正在修复...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN display_name VARCHAR(64) DEFAULT ''"))
                conn.commit()
            logger.info("users.display_name 列已添加")

    # ── roles 表：menu_permissions ──
    if "roles" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("roles")}
        if "menu_permissions" not in cols:
            logger.warning("roles 表缺少 menu_permissions 列，正在修复...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE roles ADD COLUMN menu_permissions JSON"))
                conn.commit()
            logger.info("roles.menu_permissions 列已添加")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
