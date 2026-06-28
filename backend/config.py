"""启动级环境变量：数据库连接、JWT、轮询、Redis 等。

Phase 1 新增：
- 平台 MySQL 连接（元数据 + 报价缓存 + 审计日志）
- 轮询间隔与静默超时
- Redis URL（可选）
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)


class Settings(BaseSettings):
    app_name: str = "智能报价平台"

    # ---------- 数据库 ----------
    # 默认：SQLite（开发/单机）；生产：mysql+pymysql://user:pass@host:port/db
    db_url: str = os.getenv(
        "DB_URL", f"sqlite:///{_PROJECT_ROOT / 'data' / 'app.db'}"
    )

    # ---------- JWT ----------
    jwt_secret: str = os.getenv(
        "JWT_SECRET", "change-me-to-a-long-random-string-in-production"
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", str(60 * 24)))

    # ---------- 服务 ----------
    backend_host: str = os.getenv("BACKEND_HOST", "0.0.0.0")
    backend_port: int = int(os.getenv("BACKEND_PORT", "8502"))
    api_base_url: str = os.getenv("API_BASE_URL", "http://127.0.0.1:8502")

    # ---------- 缓存（Phase 1 新增）----------
    redis_url: str = os.getenv("REDIS_URL", "")  # 为空时自动退化为内存缓存

    # ---------- 动态轮询（Phase 1 新增）----------
    polling_interval_seconds: int = int(os.getenv("POLLING_INTERVAL_SECONDS", "60"))       # 1 分钟（DB 按需同步）
    inactive_timeout_seconds: int = int(os.getenv("INACTIVE_TIMEOUT_SECONDS", "600"))       # 10 分钟静默后停止轮询
    polling_scan_seconds: int = int(os.getenv("POLLING_SCAN_SECONDS", "30"))                # 每 30s 扫描一次活跃状态


settings = Settings()
