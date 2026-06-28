"""统一报价服务。

负责：
1. 根据租户策略拉取数据源全量数据
2. 写入 price_cache 本地缓存表（INSERT ... ON DUPLICATE KEY UPDATE 模拟）
3. 在内存中对 price_cache 做关键词匹配
4. 更新 last_synced_at 同步时间戳
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .database import SessionLocal
from .datasource import get_strategy, DataSourceConfig
from .datasource.base import PriceItem
from .llm_service import extract_keywords_for_tenant

# UTC+8 时区（中国标准时间）
_CST = timezone(timedelta(hours=8))


def format_last_synced_utc(dt: datetime | None) -> str | None:
    """将数据库中的时间转换为 ISO 格式字符串，供 API 返回。
    
    兼容旧数据：若 dt 为 None 返回 None。
    统一存储本地时间(UTC+8)后，直接返回 ISO 格式字符串。
    
    注意：旧版本存储的是 UTC 时间，显示会有 8 小时偏差。
    自动刷新机制会在每天首次访问时更新为正确的本地时间。
    """
    if dt is None:
        return None
    # 直接返回 ISO 格式字符串，便于前端解析
    return dt.isoformat()

# 内存缓存（无 Redis 时的退化方案）
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 300  # 5 分钟

# 后台同步线程池（避免阻塞用户请求）
_sync_pool: list[threading.Thread] = []


def _cache_key(tenant_code: str) -> str:
    return f"price_cache:{tenant_code}"


def _cache_key_with_source(tenant_code: str, source_mode: str) -> str:
    return f"price_cache:{tenant_code}:{source_mode}"


def _read_cache(tenant_code: str, source_mode: str = "", min_creation_time: float = 0) -> list[dict] | None:
    """从内存缓存读取。返回 None 表示未命中。
    
    min_creation_time: 若提供，缓存创建时间必须 >= 此值才视为有效。
    用于解决多 worker 内存缓存不一致问题——当数据被刷新后，其他 worker 的旧缓存自动失效。
    """
    if settings.redis_url:
        # Redis 模式暂不实现，退回内存
        pass
    key = _cache_key_with_source(tenant_code, source_mode) if source_mode else _cache_key(tenant_code)
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and time.time() < entry["expire"]:
            # 版本校验：缓存创建时间必须 >= min_creation_time
            if min_creation_time and entry.get("creation_time", 0) < min_creation_time:
                return None
            return entry["rows"]
    return None


def _write_cache(tenant_code: str, rows: list[dict], source_mode: str = "") -> None:
    """写入内存缓存。"""
    key = _cache_key_with_source(tenant_code, source_mode) if source_mode else _cache_key(tenant_code)
    with _CACHE_LOCK:
        _CACHE[key] = {
            "rows": rows,
            "expire": time.time() + _CACHE_TTL,
            "creation_time": time.time(),
        }


def _invalidate_cache(tenant_code: str, source_mode: str = "") -> None:
    key = _cache_key_with_source(tenant_code, source_mode) if source_mode else _cache_key(tenant_code)
    with _CACHE_LOCK:
        _CACHE.pop(key, None)


def sync_from_source(db: Session, tenant_id: int, force: bool = False) -> tuple[int, str]:
    """从数据源拉取全量数据 → 写入 price_cache 表 → 更新 last_synced_at。

    Returns:
        (count, error_message) — count 为写入行数，error_message 非空表示连接/查询失败
    """
    import logging
    logger = logging.getLogger("price_service")

    strategy, ds_cfg = get_strategy(db, tenant_id)
    try:
        items = strategy.fetch_all(ds_cfg)
    except Exception as e:
        logger.error(f"sync_from_source({tenant_id}) exception: {e}")
        return 0, str(e)

    # 检查是否连接/查询失败 —— fetch_all 返回空列表可能是连接失败或查询无数据
    # 尝试快速校验以区分两种情况
    if not items:
        ok, msg = strategy.validate_config(ds_cfg)
        if not ok:
            return 0, msg
        # 连接正常但无数据（例如 ERP 当日无报价数据）
        # 仍然更新 last_synced_at 和活跃状态，避免每次都重复触发同步
        tenant_code = ds_cfg.tenant_code
        logger.info(f"sync {tenant_code}: source returned 0 rows but connection OK, updating last_synced_at")
        cfg = db.query(models.TenantConfig).filter(models.TenantConfig.tenant_id == tenant_id).first()
        if cfg:
            cfg.last_synced_at = datetime.now(_CST).replace(tzinfo=None)
            db.commit()
            logger.info(f"sync_from_source({tenant_id}): last_synced_at updated to {cfg.last_synced_at} (0 rows)")
        _touch_activity(db, tenant_code)
        # 清除内存缓存，确保下次读取时从 DB 获取最新数据
        _invalidate_cache(tenant_code, ds_cfg.source_mode)
        _invalidate_cache(tenant_code, "")
        return 0, ""

    tenant_code = ds_cfg.tenant_code
    source_mode = ds_cfg.source_mode

    # 1) 先删除该商户的所有旧数据（不分 data_source，解决切换数据源后旧数据残留）
    db.execute(
        text("DELETE FROM price_cache WHERE tenant_code = :tc"),
        {"tc": tenant_code},
    )
    db.commit()
    logger.info(f"sync {tenant_code}: deleted all old cache rows for tenant, inserting {len(items)} new rows")

    # 2) 批量插入新数据（使用 bulk_insert_mappings 避免 N 次 db.add()）
    import logging
    logger2 = logging.getLogger("price_service.sync")
    t_sync = time.time()
    now = datetime.now(_CST).replace(tzinfo=None)
    batch_size = 200
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        mappings = [
            {
                "tenant_code": tenant_code,
                "source_id": item.source_id,
                "data_source": source_mode,
                "product_name": item.product_name,
                "price": item.price,
                "extra_json": item.extra_json or "{}",
                "synced_at": now,
            }
            for item in batch
        ]
        db.execute(models.PriceCache.__table__.insert(), mappings)
        db.commit()
        logger2.debug(f"sync {tenant_code}: committed batch {i // batch_size + 1}, {i + len(batch)}/{len(items)}")
    logger2.info(f"[PERF] sync_from_source({tenant_code}): inserted {len(items)} rows in {time.time()-t_sync:.3f}s")

    # 3) 更新 last_synced_at（统一存储本地时间 UTC+8）
    cfg = db.query(models.TenantConfig).filter(models.TenantConfig.tenant_id == tenant_id).first()
    if cfg:
        cfg.last_synced_at = datetime.now(_CST).replace(tzinfo=None)
        db.commit()
        logger.info(f"sync_from_source({tenant_id}): last_synced_at updated to {cfg.last_synced_at}")
    else:
        logger.warning(f"sync_from_source({tenant_id}): TenantConfig not found, cannot update last_synced_at")

    # 4) 更新活跃状态表
    _touch_activity(db, tenant_code)

    # 5) 清理内存缓存（当前 source_mode + 旧格式 key，确保切换数据源后旧缓存彻底清除）
    _invalidate_cache(tenant_code, source_mode)
    _invalidate_cache(tenant_code, "")

    return len(items), ""


def _touch_activity(db: Session, tenant_code: str) -> None:
    """更新商户活跃时间。"""
    act = db.query(models.TenantActivity).filter(
        models.TenantActivity.tenant_code == tenant_code
    ).first()
    if act:
        act.last_active_at = datetime.now(_CST).replace(tzinfo=None)
    else:
        act = models.TenantActivity(tenant_code=tenant_code, last_active_at=datetime.now(_CST).replace(tzinfo=None))
        db.add(act)
    db.commit()


def refresh_tenant_cache(db: Session, tenant_code: str, sync_wait: bool = False) -> dict:
    """公开接口：强制刷新指定商户的缓存数据。

    1. 清除内存缓存（所有数据源模式 + 旧格式 key）
    2. 清除 price_cache 表中的旧数据
    3. 同步执行数据同步（重新从数据源拉取数据）
       — sync_wait=True 时等待同步完成，确保 last_synced_at 立即更新
       — sync_wait=False 时异步执行，不阻塞用户

    供运营平台「刷新缓存」按钮调用。
    """
    import logging
    logger = logging.getLogger("price_service.refresh")

    # 强制刷新 session 缓存，确保读到最新的 tenant.source_mode（解决切换数据源后连接未更新问题）
    db.expire_all()
    tenant = db.query(models.Tenant).filter(models.Tenant.code == tenant_code).first()
    if not tenant:
        return {"ok": False, "message": "商户不存在"}
    db.refresh(tenant)

    source_mode = tenant.source_mode or "feishu"
    logger.info(f"refresh_tenant_cache: {tenant_code} — current source_mode={source_mode}")

    # 1) 清除内存缓存（所有数据源模式 + 旧格式 key，解决切换数据源后旧缓存残留）
    for mode in ("feishu", "db"):
        _invalidate_cache(tenant_code, mode)
    # 同时清除旧格式 key（不带 source_mode 后缀），防止历史数据残留
    _invalidate_cache(tenant_code, "")
    logger.info(f"refresh_tenant_cache: {tenant_code} — memory cache cleared (feishu, db, old-format)")

    # 2) 清除 DB price_cache 表中的旧数据（清除所有数据源模式，解决切换数据源后旧数据残留问题）
    result = db.execute(
        text("DELETE FROM price_cache WHERE tenant_code = :tc"),
        {"tc": tenant_code},
    )
    db.commit()
    deleted_count = result.rowcount
    logger.info(f"refresh_tenant_cache: {tenant_code} — deleted {deleted_count} old rows from price_cache (all data_sources)")

    if sync_wait:
        # 同步执行：等待同步完成，确保 last_synced_at 立即更新
        n, sync_err = sync_from_source(db, tenant.id, force=True)
        if sync_err:
            logger.error(f"refresh_tenant_cache: {tenant_code} — sync failed: {sync_err}")
            return {"ok": False, "message": f"同步失败：{sync_err}"}
        logger.info(f"refresh_tenant_cache: {tenant_code} — sync completed, {n} rows synced")
        return {"ok": True, "message": f"缓存已刷新，共 {n} 条数据"}
    else:
        # 异步执行：不阻塞用户
        _trigger_async_sync(tenant.id, tenant_code)
        logger.info(f"refresh_tenant_cache: {tenant_code} (source_mode={source_mode}) — async sync triggered")
        return {"ok": True, "message": f"缓存已清除（{deleted_count} 条旧数据），正在后台同步，请稍后刷新页面查看"}


def _trigger_async_sync(tenant_id: int, tenant_code: str) -> None:
    """在后台线程中异步执行数据同步，不阻塞用户请求。"""
    def _run():
        import logging
        logger = logging.getLogger("price_service.async_sync")
        db2 = SessionLocal()
        try:
            from . import models as _m
            n, sync_err = sync_from_source(db2, tenant_id, force=True)
            logger.info(f"async_sync {tenant_code}: synced {n} rows" + (f" (error: {sync_err})" if sync_err else ""))
        except Exception as e:
            logger.error(f"async_sync {tenant_code} failed: {e}")
        finally:
            db2.close()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _sync_pool.append(t)
    # 清理已完成的线程
    _sync_pool[:] = [t for t in _sync_pool if t.is_alive()]


def get_rows_from_cache(db: Session, tenant_code: str, force_refresh: bool = False, auto_refresh: bool = False) -> tuple[list[dict], str, int, bool]:
    """从 price_cache 表 + 内存缓存读取报价行（纯读操作，不阻塞）。

    如果缓存为空，立即返回空数据并触发后台异步同步线程，
    用户下次请求即可看到数据，不会在页面上死等。

    Args:
        auto_refresh: 如果为 True，检查数据是否过期（超过 24 小时），如果是则自动触发刷新

    Returns:
        (rows, sync_status, sync_count, auto_refreshed)
        sync_status: "ok" | "no_config" | "fetch_error" | "empty" | "syncing"
        auto_refreshed: 是否触发了自动刷新
    """
    import logging
    logger = logging.getLogger("price_service")
    t0 = time.time()
    auto_refreshed = False

    # 更新活跃状态（不阻塞请求）
    _touch_activity(db, tenant_code)

    # _touch_activity 内部调用了 db.commit()，会导致 session 中所有对象过期
    # 显式 expire_all 确保后续所有查询都从 DB 读取最新数据（解决切换数据源后配置未更新问题）
    db.expire_all()

    # 获取当前数据源模式（显式 refresh 确保读到最新值）
    tenant = db.query(models.Tenant).filter(models.Tenant.code == tenant_code).first()
    if not tenant:
        logger.warning(f"get_rows_from_cache({tenant_code}): tenant not found")
        return [], "empty", 0, False
    db.refresh(tenant)
    source_mode = tenant.source_mode if tenant else "feishu"
    logger.info(f"[PERF] get_rows_from_cache({tenant_code}): source_mode={source_mode}, force={force_refresh}, auto={auto_refresh}")

    # 获取 last_synced_at 用于校验内存缓存版本（解决多 worker 切换数据源后旧缓存残留问题）
    cfg = db.query(models.TenantConfig).filter(
        models.TenantConfig.tenant_id == tenant.id
    ).first() if tenant else None
    if cfg:
        db.refresh(cfg)
    last_synced_ts = cfg.last_synced_at.timestamp() if cfg and cfg.last_synced_at else 0
    logger.info(f"[PERF] get_rows_from_cache({tenant_code}): last_synced_ts={last_synced_ts}")

    # DB 模式跟踪同步错误，用于返回给前端提示
    _sync_error: str | None = None

    # 自动刷新检查：如果数据不是今天（UTC+8）的，或超过 2 小时未更新，触发同步刷新
    if auto_refresh and cfg:
        now_local = datetime.now(_CST).replace(tzinfo=None)
        should_refresh = False
        stale_hours = 0.0
        if not cfg.last_synced_at:
            should_refresh = True
            logger.info(f"[PERF] get_rows_from_cache({tenant_code}): last_synced_at is None, triggering sync")
        else:
            last_synced_local = cfg.last_synced_at
            stale_hours = (now_local - last_synced_local).total_seconds() / 3600
            # 触发条件：非当天数据，或当天数据超过 2 小时未更新
            if last_synced_local.date() < now_local.date():
                should_refresh = True
                logger.info(f"[PERF] get_rows_from_cache({tenant_code}): data stale (last: {last_synced_local.date()}, today: {now_local.date()}, {stale_hours:.1f}h)")
            elif stale_hours > 2.0:
                should_refresh = True
                logger.info(f"[PERF] get_rows_from_cache({tenant_code}): data stale (same day, {stale_hours:.1f}h since last sync)")

        # DB 模式：即使未超过 2 小时，也检查 ERP 实际更新时间是否比本地缓存更新
        # 解决 ERP 在两次同步之间更新了数据但本地未感知到的问题
        if not should_refresh and auto_refresh and source_mode == "db" and cfg and cfg.last_synced_at:
            try:
                from .datasource import get_strategy
                _, ds_cfg = get_strategy(db, tenant.id)
                from .datasource.db_strategy import DBDataSourceStrategy
                erp_update = DBDataSourceStrategy.get_erp_last_update(ds_cfg)
                if erp_update and erp_update > cfg.last_synced_at:
                    diff_min = (erp_update - cfg.last_synced_at).total_seconds() / 60
                    logger.info(f"[PERF] get_rows_from_cache({tenant_code}): ERP newer ({erp_update} > local {cfg.last_synced_at}, {diff_min:.0f}min), triggering sync")
                    should_refresh = True
            except Exception as e:
                logger.warning(f"[PERF] get_rows_from_cache({tenant_code}): ERP update check failed: {e}")

        if should_refresh:
            auto_refreshed = True
            # 同步执行（非异步），确保本请求就能拿到最新数据
            logger.info(f"[PERF] get_rows_from_cache({tenant_code}): performing SYNC refresh (stale={stale_hours:.1f}h)...")
            sync_count, sync_err = sync_from_source(db, tenant.id, force=True)
            if sync_err:
                logger.warning(f"[PERF] get_rows_from_cache({tenant_code}): sync refresh FAILED: {sync_err}")
                _sync_error = sync_err
            else:
                logger.info(f"[PERF] get_rows_from_cache({tenant_code}): sync refresh OK, {sync_count} rows")
                _invalidate_cache(tenant_code, source_mode)
                # 重新读取后标记 sync_status
                sync_rows = db.query(models.PriceCache).filter(
                    models.PriceCache.tenant_code == tenant_code,
                    models.PriceCache.data_source == source_mode,
                ).all()
                if sync_rows:
                    rows = sync_rows
                    sync_status = "refresh_ok"
                    sync_count = len(sync_rows)
                else:
                    sync_status = "empty"

    if force_refresh:
        if tenant:
            if source_mode == "db":
                # DB 模式：同步执行，让调用方立即感知连接异常
                # 避免异步静默失败导致用户一直使用旧数据而不自知
                _, sync_err = sync_from_source(db, tenant.id, force=True)
                if sync_err:
                    _sync_error = sync_err
                    logger.warning(f"sync_from_source({tenant_code}) DB sync failed: {_sync_error}")
                    # 同步失败：不清除缓存，继续使用旧数据
                else:
                    # 同步成功：清除内存缓存，后续从 DB 重新读取
                    _invalidate_cache(tenant_code, source_mode)
                    logger.info(f"[PERF] sync_from_source({tenant_code}): DB sync OK")
            else:
                _trigger_async_sync(tenant.id, tenant_code)
                _invalidate_cache(tenant_code, source_mode)
                logger.info(f"[PERF] force_refresh for {tenant_code}: async sync triggered")
        else:
            _invalidate_cache(tenant_code, source_mode)

    # 1) 内存缓存（按 source_mode 区分，带 last_synced_at 版本校验）
    t1 = time.time()
    mem = _read_cache(tenant_code, source_mode, min_creation_time=last_synced_ts)
    if mem is not None:
        logger.info(f"[PERF] get_rows_from_cache({tenant_code}): memory cache HIT, {len(mem)} rows, took {time.time()-t1:.3f}s")
        return mem, "ok", len(mem), auto_refreshed

    # 2) DB 缓存 —— 按当前 data_source 过滤，确保切换数据源模式后不会读到旧数据
    t2 = time.time()
    rows = db.query(models.PriceCache).filter(
        models.PriceCache.tenant_code == tenant_code,
        models.PriceCache.data_source == source_mode,
    ).all()
    logger.info(f"[PERF] get_rows_from_cache({tenant_code}): DB query took {time.time()-t2:.3f}s, {len(rows)} rows")

    # 3) 缓存为空 → 触发后台异步同步，立即返回空数据
    sync_status = "ok"
    sync_count = len(rows)
    if not rows:
        if tenant:
            # 检查是否已配置（区分「未配置」和「配置了但无数据」）
            from .datasource import get_strategy
            _, ds_cfg = get_strategy(db, tenant.id)
            if tenant.source_mode == "feishu":
                if not ds_cfg.feishu_app_id or not ds_cfg.feishu_app_secret or not ds_cfg.feishu_app_token or not ds_cfg.feishu_table_id:
                    sync_status = "no_config"
                else:
                    sync_status = "syncing"
                    _trigger_async_sync(tenant.id, tenant_code)
                    logger.info(f"[PERF] get_rows_from_cache({tenant_code}): cache empty, async sync triggered, returning empty")
            elif tenant.source_mode == "db":
                if not ds_cfg.db_url or not ds_cfg.db_username:
                    sync_status = "no_config"
                else:
                    # DB 模式：同步执行，及时返回连接错误
                    _, sync_err = sync_from_source(db, tenant.id, force=True)
                    if sync_err:
                        _sync_error = sync_err
                        sync_status = f"fetch_error|{sync_err}"
                        logger.warning(f"[PERF] get_rows_from_cache({tenant_code}): cache empty, DB sync failed: {sync_err}")
                    else:
                        # 同步成功，重新从 DB 读取新数据
                        rows = db.query(models.PriceCache).filter(
                            models.PriceCache.tenant_code == tenant_code,
                            models.PriceCache.data_source == source_mode,
                        ).all()
                        sync_status = "ok"
                        sync_count = len(rows)
                        logger.info(f"[PERF] get_rows_from_cache({tenant_code}): cache empty, DB sync OK, got {len(rows)} rows")
            else:
                sync_status = "empty"
        else:
            sync_status = "empty"

    # 4) 构建返回结果
    t3 = time.time()
    result: list[dict] = []
    for r in rows:
        result.append({
            "source_id": r.source_id,
            "product_name": r.product_name,
            "price": r.price,
            "data_source": r.data_source,
            "extra_json": r.extra_json or "{}",
        })
    logger.info(f"[PERF] get_rows_from_cache({tenant_code}): build {len(result)} dicts took {time.time()-t3:.3f}s, total={time.time()-t0:.3f}s")

    # 写入内存缓存（仅在有数据时写入，空结果不缓存，确保后续请求能重新查询 DB）
    if result:
        _write_cache(tenant_code, result, source_mode)

    # DB 模式同步失败时覆盖 sync_status，让前端展示具体错误
    if _sync_error:
        sync_status = f"fetch_error|{_sync_error}"

    return result, sync_status, sync_count, auto_refreshed


def search_price_in_cache(
    db: Session,
    tenant_code: str,
    product_field_name: str,
    price_field_name: str,
    keywords: list[str],
    price_field: Optional[str] = None,
    auto_refresh: bool = False,
) -> tuple[Optional[str], Optional[str], str, int]:
    """在缓存中按关键词搜索报价。

    Args:
        price_field: 指定报价等级字段名（如 "jg2", "jg4"），若提供则从 extra_json 的 price_map 中取对应报价
        auto_refresh: 如果为 True，检查数据是否过期（超过 24 小时），如果是则自动触发刷新

    Returns:
        (price, matched_name, sync_status, sync_count)
        sync_status: "ok" | "no_config" | "fetch_error" | "empty"
    """
    rows, sync_status, sync_count, _ = get_rows_from_cache(db, tenant_code, auto_refresh=auto_refresh)
    if not rows or not keywords:
        return None, None, sync_status, sync_count

    price, matched_name = _search_in_rows(rows, product_field_name, price_field_name, keywords, price_field)
    return price, matched_name, sync_status, sync_count


def _has_color_keyword(keywords: list[str]) -> bool:
    """判断关键词列表中是否包含颜色关键词。"""
    from .feishu_api import _is_color_keyword, _split_packed_color_tokens
    # 先展开粘连颜色词：粉黑金 → [粉, 黑, 金]
    expanded = _split_packed_color_tokens(keywords)
    return any(_is_color_keyword(k) for k in expanded)


def search_price_in_rows(
    rows: list[dict],
    product_field_name: str,
    price_field_name: str,
    keywords: list[str],
    price_field: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """在已预取的 rows 中按关键词搜索报价（复用已获取的缓存数据，避免重复查询）。

    Args:
        rows: 从 get_rows_from_cache 获取的原始行列表
        product_field_name: 商品名称字段名
        price_field_name: 报价字段名
        keywords: 关键词列表
        price_field: 指定报价等级字段名（如 "jg2", "jg4"），若提供则从 extra_json 的 price_map 中取对应报价

    Returns:
        (price, matched_name)
    """
    if not rows or not keywords:
        return None, None

    price, matched_name = _search_in_rows(rows, product_field_name, price_field_name, keywords, price_field)
    return price, matched_name


def search_price_in_rows_batch(
    rows: list[dict],
    product_field_name: str,
    price_field_name: str,
    all_keywords: list[list[str]],
    price_field: Optional[str] = None,
) -> list[tuple[Optional[str], Optional[str]]]:
    """批量搜索：预计算归一化数据，一次遍历处理所有行的关键词。

    相比逐行调用 search_price_in_rows，避免了每行都重新格式化 rows 和归一化名称，
    显著减少 CPU 开销（尤其是 rows 数量大时）。

    Args:
        rows: 从 get_rows_from_cache 获取的原始行列表
        product_field_name: 商品名称字段名
        price_field_name: 报价字段名
        all_keywords: 每行输入的关键词列表（与输入行一一对应）
        price_field: 指定报价等级字段名

    Returns:
        [(price, matched_name), ...] 与 all_keywords 等长
    """
    if not rows or not all_keywords:
        return [(None, None)] * len(all_keywords)

    from .feishu_api import match_keywords_in_rows_batch

    # 格式化 rows 为匹配函数需要的格式（保留 extra_json 供 price_field 查价格映射用）
    formatted: list[dict] = []
    for r in rows:
        formatted.append({
            product_field_name: r["product_name"],
            price_field_name: r["price"],
            "extra_json": r.get("extra_json", "{}") or "{}",
        })

    return match_keywords_in_rows_batch(
        formatted, product_field_name, price_field_name, all_keywords, price_field
    )


def _search_in_rows(
    rows: list[dict],
    product_field_name: str,
    price_field_name: str,
    keywords: list[str],
    price_field: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """内部实现：在 rows 中搜索，返回 (price, matched_name)。"""
    # 转换为 feishu_api 需要的格式（dict with field_name → value）
    formatted: list[dict] = []
    for r in rows:
        formatted.append({
            product_field_name: r["product_name"],
            price_field_name: r["price"],
        })

    # 使用独立的关键词匹配函数，直接搜索本地缓存数据
    from .feishu_api import match_keywords_in_rows, match_keywords_in_rows_with_index
    best_idx, price, matched_name = match_keywords_in_rows_with_index(
        formatted, product_field_name, price_field_name, keywords
    )
    import logging
    _log = logging.getLogger("price_service.match")
    _log.info(f"search_price_in_cache: best_idx={best_idx}, price={repr(price)}, matched_name={matched_name}, price_field={repr(price_field)}")
    if price is not None and price_field:
        # 尝试从 extra_json 的 price_map 中取指定等级的报价
        if best_idx is not None and best_idx < len(rows):
            import json as _json
            try:
                extra = _json.loads(rows[best_idx].get("extra_json", "{}") or "{}")
                pm = extra.get("price_map", {})
                _log.info(f"price_map: pm={pm}, price_field={price_field}, pm[price_field]={repr(pm.get(price_field))}")
                if price_field in pm and pm[price_field]:
                    price = pm[price_field]
                    _log.info(f"price_map: overwrote price to {repr(price)}")
            except Exception as e:
                _log.error(f"price_map error: {e}")
    return price, matched_name
