"""首次启动前运行：建表 + 插入默认 admin 租户 + admin 管理员账号。

默认登录信息：
    公司代码：admin
    用户名：  admin
    密码：    admin123

用法（两种方式均可）：
    python -m backend.init_db          # 在项目根目录执行
    python3 backend/init_db.py         # 在项目根目录执行
    python3 init_db.py                 # 在 backend 目录执行
"""

from __future__ import annotations

import os
import sys

# 将项目根目录（backend 的父目录）加入 sys.path，确保无论以何种方式运行都能正确导入 backend 模块
_backend_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend import models, auth, database  # noqa: F401  确保模型 & 模块被注册
from backend.auth import hash_password
from backend.database import Base, SessionLocal, engine


def main() -> None:
    # 1) 建表
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # 2) 角色（admin / user）
        roles = {r.name: r for r in db.query(models.Role).all()}
        for name, desc in (("admin", "管理员"), ("user", "普通业务员")):
            if name not in roles:
                db.add(models.Role(name=name, description=desc))
        db.commit()

        # 3) 默认租户 admin
        tenant = db.query(models.Tenant).filter(models.Tenant.code == "admin").first()
        if not tenant:
            tenant = models.Tenant(code="admin", name="默认演示公司")
            db.add(tenant)
            db.commit()
            db.refresh(tenant)

        # 4) 默认用户 admin / admin123
        admin_role = db.query(models.Role).filter(models.Role.name == "admin").first()
        admin_user = (
            db.query(models.User)
            .filter(models.User.tenant_id == tenant.id, models.User.username == "admin")
            .first()
        )
        if not admin_user:
            admin_user = models.User(
                tenant_id=tenant.id,
                role_id=admin_role.id,
                username="admin",
                password_hash=hash_password("admin123"),
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)

        # 5) 初始化一条空的 TenantConfig
        cfg = (
            db.query(models.TenantConfig)
            .filter(models.TenantConfig.tenant_id == tenant.id)
            .first()
        )
        if not cfg:
            db.add(models.TenantConfig(tenant_id=tenant.id))
            db.commit()

        print("✅ 数据库初始化完成。")
        print("   默认登录：公司代码=admin, 用户名=admin, 密码=admin123")
    finally:
        db.close()


if __name__ == "__main__":
    main()
