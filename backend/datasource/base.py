"""数据源策略抽象基类 + 统一报价数据模型。

所有数据源策略（飞书 / DB 直连）均实现此接口，
下游（PriceService / 轮询调度器）只需面向 DataSourceStrategy 编程。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class PriceItem:
    """统一报价数据模型 —— 无论飞书还是 DB 直连，最终都转为此结构。"""
    source_id: str                        # 原始数据源行唯一 ID（飞书 record_id / DB 主键）
    product_name: str                     # 商品名称
    price: str                            # 报价
    data_source: str = "feishu"           # "feishu" | "db"
    tenant_code: str = ""                 # 多租户隔离标识
    extra_json: str = "{}"                # 其它字段（JSON 字符串）


@dataclass
class DataSourceConfig:
    """策略运行时配置 —— 从 TenantConfig 中提取并组装。"""
    tenant_code: str = ""
    source_mode: str = "feishu"           # "feishu" | "db"

    # 飞书参数
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_app_token: str = ""
    feishu_table_id: str = ""
    feishu_field_name: str = "商品名称"
    feishu_price_field_name: str = "报价"

    # DB 直连参数
    db_url: str = ""
    db_username: str = ""
    db_password: str = ""
    db_company_code: str = ""
    price_date: str = ""  # 报价日期，为空则取当日

    # 报价等级配置（JSON 列表）
    price_fields: list | None = None  # [{"label":"价格1","field":"jg2","enabled":true}, ...]


class DataSourceStrategy(ABC):
    """数据源策略抽象基类。

    子类必须实现:
      - fetch_all()       全量拉取
      - validate_config() 配置校验
    """

    @abstractmethod
    def fetch_all(self, cfg: DataSourceConfig) -> List[PriceItem]:
        """全量拉取数据源所有报价行。

        Returns:
            PriceItem 列表，若连接失败返回空列表
        """
        ...

    @abstractmethod
    def validate_config(self, cfg: DataSourceConfig) -> tuple[bool, str]:
        """校验配置是否可用（连通性测试）。

        Returns:
            (ok, message) — ok=True 表示可连接
        """
        ...

    def check_has_update(self, cfg: DataSourceConfig, last_synced_at: datetime | None) -> bool:
        """检查数据源是否有变更（用于增量轮询）。

        默认实现：始终返回 True（每次都全量同步）。
        子类可覆盖以实现真正的增量检查。
        """
        return True
