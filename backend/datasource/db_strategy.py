"""数据库直连数据源策略。

通过 PyMySQL 动态连接商户 ERP 数据库，执行标准报价抽取 SQL。
支持连接/查询失败重试 + 异常落日志。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import List

from .base import DataSourceConfig, DataSourceStrategy, PriceItem

logger = logging.getLogger("db_strategy")

# ── 标准 ERP 报价抽取 SQL（预编译安全，%(company_code)s 为 pymysql 参数化占位符） ──
# dm_spxx = 商品信息表   b2b_bjd = 报价单明细表
# 表名、列名、关联逻辑均为固定脚本，不可通过前端配置修改
ERP_PRICE_SQL = """
SELECT
    s.pp       AS `品牌`,
    s.name     AS `商品型号`,
    s.color    AS `颜色`,
    s.fullname AS `商品名称`,
    b.jg2      AS `jg2`,
    b.jg4      AS `jg4`,
    b.jg5      AS `jg5`,
    k.kmsl     AS `库存数量`,
    b.kccb     AS `库存成本`
FROM dm_spxx s
INNER JOIN b2b_bjd b ON s.tid = b.spdm
LEFT JOIN v_get_kmsl k ON s.tid = k.spdm
WHERE
    s.gsdm = %(company_code)s
    AND s.yxbz = 'Y'
    AND b.gsdm = %(company_code)s
    AND b.fsrq = {price_date_sql}
"""

MAX_RETRIES = 2       # 最大重试次数
RETRY_DELAY_SEC = 3    # 重试间隔（秒）


def _fmt_price(val) -> str:
    """将数值格式化为字符串，去掉无意义的小数尾零（如 1890.0 → 1890，1890.5 保持不变）。"""
    if val is None or val == "":
        return ""
    s = str(val).strip()
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# ── 连接串解析 ──
def _parse_db_url(db_url: str, username: str, password: str) -> dict:
    """解析 JDBC/MySQL URL 或 host:port/db，返回 pymysql.connect() kwargs。

    支持格式：
      jdbc:mysql://192.168.80.102:3433/db1790
      mysql://192.168.80.102:3433/db1790
      192.168.80.102:3433/db1790
    """
    url = db_url.strip()
    url = re.sub(r'^jdbc:', '', url)
    url = re.sub(r'^mysql://', '', url)
    m = re.match(r'^([^:/]+):(\d+)/(.+)$', url)
    if not m:
        return {}
    database = m.group(3)
    # 去掉 JDBC URL 中的查询参数（如 ?useUnicode=yes&...），否则会被当成数据库名
    database = database.split('?')[0]
    return {
        "host": m.group(1),
        "port": int(m.group(2)),
        "database": database,
        "user": username,
        "password": password,
        "charset": "utf8mb4",
        "connect_timeout": 10,
        "read_timeout": 30,
    }


# ── 策略实现 ──
class DBDataSourceStrategy(DataSourceStrategy):
    """策略 B：数据库直连（ERP 标准报价抽取）。"""

    def __init__(self):
        self.last_sql = ""  # 记录最后一次执行的 SQL，便于排查

    def _connect(self, cfg: DataSourceConfig):
        """建立 ERP DB 连接，返回 (conn, cursor)，失败返回 (None, None)。"""
        kwargs = _parse_db_url(cfg.db_url, cfg.db_username, cfg.db_password)
        if not kwargs:
            return None, None
        import pymysql
        conn = pymysql.connect(**kwargs)
        return conn, conn.cursor()

    # ------------------------------------------------------------------
    def fetch_all(self, cfg: DataSourceConfig) -> List[PriceItem]:
        company_code = cfg.db_company_code or cfg.tenant_code
        # 报价日期：已配置则用配置值，否则用 CURDATE()
        price_date_param = (cfg.price_date or "").strip()
        if price_date_param:
            price_date_sql = "%(price_date)s"
            price_date_value = price_date_param
        else:
            price_date_sql = "CURDATE()"
            price_date_value = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                conn, cursor = self._connect(cfg)
            except Exception as e:
                logger.error(f"[{company_code}] DB 连接失败（第 {attempt+1} 次）: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SEC)
                continue

            if conn is None:
                logger.error(f"[{company_code}] DB 连接串无法解析: {cfg.db_url}")
                return []

            try:
                # 构建 SQL（替换日期占位符）
                sql = ERP_PRICE_SQL.format(price_date_sql=price_date_sql)
                params = {"company_code": company_code}
                if price_date_value:
                    params["price_date"] = price_date_value
                # 打印实际执行的 SQL
                import pymysql
                final_sql = cursor.mogrify(sql, params)
                self.last_sql = final_sql
                logger.info(f"[{company_code}] 执行 SQL:\n{final_sql}")
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                logger.info(f"[{company_code}] 查询返回 {len(rows)} 行")
                if not rows:
                    logger.warning(f"[{company_code}] 查询返回 0 行，SQL:\n{final_sql}")
            except Exception as e:
                logger.error(f"[{company_code}] DB 查询失败（第 {attempt+1} 次）: {e}")
                if attempt < MAX_RETRIES:
                    conn.close()
                    time.sleep(RETRY_DELAY_SEC)
                    continue
                conn.close()
                return []
            finally:
                # 此处 finally 仅负责在正常流程或非重试场景关连接
                pass

            items: List[PriceItem] = []
            for i, row in enumerate(rows):
                # row[3] = 商品名称 (s.fullname)
                name = (row[3] or "").strip()
                if not name:
                    continue
                # 构建报价字段映射（供前端按 price_field 查询）
                # row[4]=价格0(jg2), row[5]=价格1(jg4), row[6]=价格2(jg5)
                all_prices = {
                    "jg2": _fmt_price(row[4]),
                    "jg4": _fmt_price(row[5]),
                    "jg5": _fmt_price(row[6]),
                }
                # 根据 price_fields 配置构建 price_map，尊重用户的字段映射
                price_map = {}
                if cfg.price_fields:
                    for pf in cfg.price_fields:
                        field = pf.get("field", "")
                        label = pf.get("label", "")
                        if not field:
                            continue
                        # 优先从 all_prices 取（标准 ERP 字段），其次从 extra 取
                        val = all_prices.get(field, "")
                        if not val and label:
                            val = all_prices.get(label, "")
                        price_map[field] = val
                else:
                    # 无配置时使用默认映射
                    price_map = dict(all_prices)

                # 默认报价：优先取第一个启用的价格字段，其次 jg4/jg5
                price = ""
                if cfg.price_fields:
                    enabled_pfs = [pf for pf in cfg.price_fields if pf.get("enabled")]
                    if enabled_pfs:
                        first_field = enabled_pfs[0].get("field", "")
                        price = all_prices.get(first_field, "")
                        if not price and enabled_pfs[0].get("label"):
                            price = all_prices.get(enabled_pfs[0]["label"], "")
                if not price:
                    price = _fmt_price(row[5]) or _fmt_price(row[6])

                extra = json.dumps({
                    "品牌":       row[0] or "",
                    "商品型号":   row[1] or "",
                    "颜色":       row[2] or "",
                    "jg2":        _fmt_price(row[4]),
                    "jg4":        _fmt_price(row[5]),
                    "jg5":        _fmt_price(row[6]),
                    "库存数量":   _fmt_price(row[7]),
                    "库存成本":   _fmt_price(row[8]),
                    "price_map":  price_map,
                }, ensure_ascii=False)
                source_id = f"db_{company_code}_{i}_{name[:60]}"
                items.append(PriceItem(
                    source_id=source_id,
                    product_name=name,
                    price=price,
                    data_source="db",
                    tenant_code=company_code,
                    extra_json=extra,
                ))

            conn.close()
            logger.info(f"[{company_code}] DB 同步完成，共 {len(items)} 行")
            return items

        # 所有重试均失败
        logger.error(f"商户 [{company_code}] 数据库连接异常（重试 {MAX_RETRIES} 次后仍失败）")
        return []

    # ------------------------------------------------------------------
    def validate_config(self, cfg: DataSourceConfig) -> tuple[bool, str]:
        if not cfg.db_url or not cfg.db_username:
            return False, "数据库连接串 / 用户名未填写"
        kwargs = _parse_db_url(cfg.db_url, cfg.db_username, cfg.db_password)
        if not kwargs:
            return False, "数据库连接串格式不正确（示例: 192.168.80.102:3433/db1790）"
        try:
            import pymysql
            conn = pymysql.connect(**kwargs)
            conn.close()
            return True, "ERP 数据库连接正常"
        except Exception as e:
            return False, f"数据库连接失败: {e}"

    # ------------------------------------------------------------------
    @staticmethod
    def check_recent_update(cfg: DataSourceConfig, within_seconds: int = 60) -> tuple[bool, str]:
        """按需同步检查：查询 ERP 报价单的最后更新时间，判断是否需要触发同步。

        执行 SQL：
            SELECT MAX(xgrq) FROM b2b_bjd
            WHERE fsrq = '报价动态日期' AND gsdm = '商户代码'

        Args:
            cfg: 数据源配置
            within_seconds: 若最后更新时间与当前时间差在此范围内，视为「最近有更新」

        Returns:
            (has_recent_update, message)
            - has_recent_update=True: 最近有更新，应触发同步
            - has_recent_update=False: 无近期更新，跳过本次同步（含连接失败等情况）
        """
        company_code = cfg.db_company_code or cfg.tenant_code
        price_date_param = (cfg.price_date or "").strip()
        if price_date_param:
            price_date_sql = "%(price_date)s"
            price_date_value = price_date_param
        else:
            price_date_sql = "CURDATE()"
            price_date_value = None

        sql = f"""
            SELECT MAX(xgrq) FROM b2b_bjd
            WHERE fsrq = {price_date_sql} AND gsdm = %(company_code)s
        """

        kwargs = _parse_db_url(cfg.db_url, cfg.db_username, cfg.db_password)
        if not kwargs:
            return False, "DB 连接串解析失败"

        import pymysql
        try:
            conn = pymysql.connect(**kwargs)
            cursor = conn.cursor()
            params = {"company_code": company_code}
            if price_date_value:
                params["price_date"] = price_date_value
            cursor.execute(sql, params)
            row = cursor.fetchone()
            conn.close()

            if not row or row[0] is None:
                return False, "ERP 报价单无更新时间记录"

            last_update = row[0]
            # ERP 的 xgrq 字段可能是 VARCHAR 类型，返回字符串
            if isinstance(last_update, datetime):
                erp_dt = last_update
            elif isinstance(last_update, str):
                val_stripped = last_update.strip()
                for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                    try:
                        erp_dt = datetime.strptime(val_stripped, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    return False, f"ERP 更新时间格式异常（无法解析字符串）: {last_update}"
            else:
                return False, f"ERP 更新时间格式异常（未知类型 {type(last_update)}）: {last_update}"

            now = datetime.now()
            diff_seconds = (now - erp_dt).total_seconds()
            if diff_seconds <= within_seconds:
                return True, f"ERP 最近 {int(diff_seconds)}s 内有更新 (last={erp_dt})"
            else:
                return False, f"ERP 最后更新于 {erp_dt}，距现在 {int(diff_seconds)}s，跳过同步"

        except Exception as e:
            # 连接/查询失败时不阻塞，直接触发同步（保底行为）
            logger.warning(f"[{company_code}] 检查 ERP 更新时间失败: {e}，将触发同步")
            return True, f"检查失败({e})，默认触发同步"

    # ------------------------------------------------------------------
    @staticmethod
    def get_erp_last_update(cfg: DataSourceConfig) -> datetime | None:
        """查询 ERP 报价单的实际最后更新时间（MAX(xgrq)）。

        执行 SQL：
            SELECT MAX(xgrq) FROM b2b_bjd
            WHERE fsrq = '报价动态日期' AND gsdm = '商户代码'

        Returns:
            ERP 最后更新时间（datetime），查询失败返回 None
        """
        company_code = cfg.db_company_code or cfg.tenant_code
        price_date_param = (cfg.price_date or "").strip()
        if price_date_param:
            price_date_sql = "%(price_date)s"
            price_date_value = price_date_param
        else:
            price_date_sql = "CURDATE()"
            price_date_value = None

        sql = f"""
            SELECT MAX(xgrq) FROM b2b_bjd
            WHERE fsrq = {price_date_sql} AND gsdm = %(company_code)s
        """

        kwargs = _parse_db_url(cfg.db_url, cfg.db_username, cfg.db_password)
        if not kwargs:
            logger.warning(f"[{company_code}] get_erp_last_update: 无法解析 DB URL: {cfg.db_url}")
            return None

        import pymysql
        try:
            conn = pymysql.connect(**kwargs)
            cursor = conn.cursor()
            params = {"company_code": company_code}
            if price_date_value:
                params["price_date"] = price_date_value
            final_sql = cursor.mogrify(sql, params)
            logger.info(f"[{company_code}] get_erp_last_update SQL: {final_sql}")
            cursor.execute(sql, params)
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                val = row[0]
                # ERP 的 xgrq 字段可能是 VARCHAR 类型，返回字符串而非 datetime
                if isinstance(val, datetime):
                    erp_dt = val
                elif isinstance(val, str):
                    # 尝试解析常见格式：'2026-06-28 15:22:39' 或 '2026-06-28'
                    val_stripped = val.strip()
                    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                        try:
                            erp_dt = datetime.strptime(val_stripped, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        logger.warning(f"[{company_code}] get_erp_last_update: 无法解析时间字符串: {val}")
                        return None
                else:
                    logger.warning(f"[{company_code}] get_erp_last_update: 未知类型 {type(val)}: {val}")
                    return None
                logger.info(f"[{company_code}] get_erp_last_update: ERP 最后更新 = {erp_dt}")
                return erp_dt
            logger.info(f"[{company_code}] get_erp_last_update: 查询返回空 (row={row})")
            return None
        except Exception as e:
            logger.warning(f"[{company_code}] get_erp_last_update 查询 ERP 更新时间失败: {type(e).__name__}: {e}")
            return None