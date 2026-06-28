"""飞书多维表格数据源策略。

封装现有 TenantFeishuClient，实现 DataSourceStrategy 接口。
业务逻辑 100% 保持不变。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List

from .base import DataSourceConfig, DataSourceStrategy, PriceItem
from ..feishu_api import TenantFeishuClient

# UTC+8 时区（中国标准时间）
_CST = timezone(timedelta(hours=8))


# 轻量适配器：把 TenantConfig ORM 对象包装为 feishu_api.py 需要的接口
class _FeishuCfgProxy:
    def __init__(self, cfg: DataSourceConfig):
        self.feishu_app_id = cfg.feishu_app_id
        self.feishu_app_secret = cfg.feishu_app_secret
        self.feishu_app_token = cfg.feishu_app_token
        self.feishu_table_id = cfg.feishu_table_id
        self.feishu_field_name = cfg.feishu_field_name
        self.feishu_price_field_name = cfg.feishu_price_field_name


class FeishuDataSourceStrategy(DataSourceStrategy):
    """策略 A：飞书多维表格。"""

    def fetch_all(self, cfg: DataSourceConfig) -> List[PriceItem]:
        import logging
        logger = logging.getLogger("feishu_strategy")
        client = TenantFeishuClient(_FeishuCfgProxy(cfg))
        if not client.configured():
            logger.warning(f"tenant={cfg.tenant_code} feishu not configured, returning empty")
            return []
        try:
            rows = client.fetch_all_rows(force=True) or []
        except Exception as e:
            logger.error(f"tenant={cfg.tenant_code} feishu fetch_all_rows failed: {e}")
            return []

        items: List[PriceItem] = []
        price_fields = cfg.price_fields or []
        # 当配置了 price_fields 时，price 取第一个启用价格字段的值；否则取默认报价列
        enabled_pfs = [pf for pf in price_fields if pf.get("enabled")]
        first_enabled_field = enabled_pfs[0].get("field", "") if enabled_pfs else ""
        for i, row in enumerate(rows):
            name = (row.get(cfg.feishu_field_name) or "").strip()
            if first_enabled_field:
                # 有 price_fields 配置时，优先取配置的价格字段，不存在则回退到 label，再回退到主报价列
                # 使用 dict.get(key) 检查 None 而非 'or' 短路，避免 price=0 被误判为 falsy 丢失
                val = row.get(first_enabled_field)
                if val is None:
                    val = row.get(enabled_pfs[0].get("label", ""), row.get(cfg.feishu_price_field_name, ""))
                price = _fmt_price(val)
            else:
                price = _fmt_price(row.get(cfg.feishu_price_field_name, ""))
            if not name:
                continue
            # 用行索引 + 商品名作为 source_id
            source_id = f"feishu_{cfg.tenant_code}_{i}_{name[:60]}"
            items.append(PriceItem(
                source_id=source_id,
                product_name=name,
                price=price or "",
                data_source="feishu",
                tenant_code=cfg.tenant_code,
                extra_json=_rows_to_json(row, price_fields, cfg.feishu_price_field_name),
            ))
        return items

    def validate_config(self, cfg: DataSourceConfig) -> tuple[bool, str]:
        if not cfg.feishu_app_id or not cfg.feishu_app_secret:
            return False, "飞书 App ID / App Secret 未填写"
        if not cfg.feishu_app_token or not cfg.feishu_table_id:
            return False, "飞书 App Token / Table ID 未填写"
        client = TenantFeishuClient(_FeishuCfgProxy(cfg))
        token = client.get_token()
        if not token:
            return False, "飞书凭证无效，请检查 App ID / App Secret"
        return True, "飞书连接正常"

    def check_has_update(self, cfg: DataSourceConfig, last_synced_at: datetime | None) -> bool:
        if last_synced_at is None:
            return True
        # 飞书：超过 polling_interval 就全量重拉
        from ..config import settings
        elapsed = (datetime.now(_CST).replace(tzinfo=None) - last_synced_at).total_seconds()
        return elapsed >= settings.polling_interval_seconds


def _fmt_price(val) -> str:
    """将数值格式化为字符串，去掉无意义的小数尾零（如 1890.0 → 1890，1890.5 保持不变）。"""
    if val is None or val == "":
        return ""
    s = str(val).strip()
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _rows_to_json(row: dict, price_fields: list | None = None, default_price_field: str = "") -> str:
    """将飞书行记录序列化为 JSON 字符串，同时构建 price_map 支持多级报价。

    price_fields: 如 [{"label":"价格1","field":"jg2","enabled":true}, ...]
    构建的 price_map 优先按 field 名匹配飞书列，其次按 label 名匹配。
    不再回退到 default_price_field，确保用户配置的字段名被严格使用。
    """
    import json
    try:
        data = dict(row)
        if price_fields:
            price_map = {}
            for pf in price_fields:
                field = pf.get("field", "")
                label = pf.get("label", "")
                if not field:
                    continue
                # 严格按 field 名取值，其次按 label 名取值，不再回退到默认报价列
                # 使用 dict.get(key, default) 而非 'or' 短路，避免 price=0 被误判为 falsy 丢失
                val = row.get(field, row.get(label, ""))
                price_map[field] = _fmt_price(val)
            data["price_map"] = price_map
        text = json.dumps(data, ensure_ascii=False, default=str)
        return text[:8192]
    except Exception:
        return "{}"
