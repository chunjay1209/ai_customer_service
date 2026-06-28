"""动态轮询调度器。

策略（"在场证明"机制）：
1. 每 30s 扫描 tenant_activity 表
2. 如果 last_active_at 在 inactive_timeout 内 → 该商户有活跃用户
   - 如果上次同步时间超过 polling_interval → 从数据源拉取全量数据写入 price_cache
3. 如果 last_active_at 超过 inactive_timeout → 静默（停止轮询）

启动方式（在 main.py 中）:
  from .polling import start_polling_scheduler
  @app.on_event("startup")
  def on_startup():
      start_polling_scheduler()
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from .config import settings
from .database import SessionLocal

# UTC+8 时区（中国标准时间）
_CST = timezone(timedelta(hours=8))

logger = logging.getLogger("polling")

_scheduler_started = False
_scan_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _scan():
    """后台扫描线程：周期检查活跃商户并触发同步。"""
    logger.info(
        "轮询调度器启动 — scan=%ds, interval=%ds, timeout=%ds",
        settings.polling_scan_seconds,
        settings.polling_interval_seconds,
        settings.inactive_timeout_seconds,
    )

    while not _stop_event.wait(timeout=settings.polling_scan_seconds):
        db = SessionLocal()
        try:
            from . import models, price_service

            now = datetime.now(_CST).replace(tzinfo=None)
            active_threshold = now - timedelta(seconds=settings.inactive_timeout_seconds)
            sync_threshold = now - timedelta(seconds=settings.polling_interval_seconds)

            # 查找活跃商户（last_active_at 在静默超时内 且 一个轮询周期内未同步）
            active_activities = db.query(models.TenantActivity).filter(
                models.TenantActivity.last_active_at >= active_threshold,
                models.TenantActivity.polling == 0,
            ).all()

            for act in active_activities:
                tenant_code = act.tenant_code
                # 检查是否需要同步
                tenant = db.query(models.Tenant).filter(
                    models.Tenant.code == tenant_code
                ).first()
                if not tenant:
                    continue

                cfg = db.query(models.TenantConfig).filter(
                    models.TenantConfig.tenant_id == tenant.id
                ).first()

                need_sync = True
                if cfg and cfg.last_synced_at:
                    if cfg.last_synced_at > sync_threshold:
                        need_sync = False

                # DB 直连模式：按需同步检查（检查 ERP 报价单是否有近期更新）
                if need_sync and tenant.source_mode == "db":
                    from .datasource import get_strategy
                    _, ds_cfg = get_strategy(db, tenant.id)
                    from .datasource.db_strategy import DBDataSourceStrategy
                    has_update, check_msg = DBDataSourceStrategy.check_recent_update(ds_cfg, within_seconds=60)
                    if not has_update:
                        logger.info("轮询跳过 %s（DB按需检查）: %s", tenant_code, check_msg)
                        need_sync = False

                if not need_sync:
                    continue

                # 标记为正在轮询
                act.polling = 1
                db.commit()

                try:
                    count, sync_err = price_service.sync_from_source(db, tenant.id)
                    logger.info("轮询同步完成 tenant=%s rows=%d", tenant_code, count)
                    if sync_err:
                        logger.warning("轮询同步异常 tenant=%s: %s", tenant_code, sync_err)
                except Exception as e:
                    logger.error("轮询同步失败 tenant=%s: %s", tenant_code, e)
                finally:
                    act.polling = 0
                    db.commit()

            # 清理标记（防止 error 时未重置）
            stuck = db.query(models.TenantActivity).filter(
                models.TenantActivity.polling == 1,
                models.TenantActivity.last_active_at < (now - timedelta(minutes=10)),
            ).all()
            for act in stuck:
                act.polling = 0
                db.commit()

        except Exception as exc:
            logger.exception("轮询扫描异常: %s", exc)
        finally:
            db.close()


def start_polling_scheduler():
    global _scheduler_started, _scan_thread
    if _scheduler_started:
        return
    _scheduler_started = True
    _scan_thread = threading.Thread(target=_scan, daemon=True, name="polling-scanner")
    _scan_thread.start()
    logger.info("动态轮询调度器已启动")


def stop_polling_scheduler():
    _stop_event.set()
    if _scan_thread and _scan_thread.is_alive():
        _scan_thread.join(timeout=5)
