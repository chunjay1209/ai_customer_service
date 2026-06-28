"""认证/鉴权工具：密码哈希、JWT、获取当前用户、RBAC 校验。

角色体系（Role.name）：
- platform_admin：超级运营管理员（byadmin / by@123），不归属于任何业务商户，
                 登录时不校验商户启用状态；
- tenant_admin ：商户管理员（自动生成：admin / 123456）；
- sales         ：普通业务员。

登录准入规则：
- 公司代码为空（或为特殊字符串 "BYADMIN" / "byadmin"）时按 platform_admin 匹配；
- 其他情况下按普通商户用户登录，并强制要求该商户 is_active == 1。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from . import models

PLATFORM_TENANT_CODES = {"", "byadmin", "BYADMIN"}

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(pwd: str) -> str:
    return pwd_ctx.hash(pwd)


def verify_password(pwd: str, hashed: str) -> bool:
    return pwd_ctx.verify(pwd, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dict(data)
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        return None


def authenticate_user(db: Session, tenant_code: str, username: str, password: str):
    """根据 tenant_code 路由走平台管理员或普通商户用户；返回 (user, role_name, tenant)。"""
    if (tenant_code or "").strip() in PLATFORM_TENANT_CODES:
        # 平台管理员：必须 username == byadmin，且 password 匹配
        user = (
            db.query(models.User)
            .join(models.Tenant, models.User.tenant_id == models.Tenant.id)
            .join(models.Role, models.User.role_id == models.Role.id)
            .filter(
                models.User.username == "byadmin",
                models.Role.name == "platform_admin",
            )
            .first()
        )
        if not user or not verify_password(password, user.password_hash):
            return None
        return user

    # 商户用户
    tenant = db.query(models.Tenant).filter(models.Tenant.code == tenant_code).first()
    if not tenant:
        return None
    if not tenant.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该商户已被停用，请联系客服")
    user = (
        db.query(models.User)
        .filter(
            models.User.tenant_id == tenant.id,
            models.User.username == username,
        )
        .first()
    )
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    payload = _decode_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录凭证无效")
    user = db.query(models.User).filter(models.User.id == int(payload["user_id"])).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    # 登录后仍然需要校验商户启用状态（避免 token 期间被停用）
    tenant = db.query(models.Tenant).filter(models.Tenant.id == user.tenant_id).first()
    role = db.query(models.Role).filter(models.Role.id == user.role_id).first()
    if role and role.name != "platform_admin":
        if not tenant or not tenant.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "该商户已被停用，请联系客服")
    return user


def _role_of(user: models.User, db: Session) -> Optional[str]:
    role = db.query(models.Role).filter(models.Role.id == user.role_id).first()
    return role.name if role else None


def require_platform_admin(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> models.User:
    if _role_of(user, db) != "platform_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅平台运营管理员可访问")
    return user


def require_tenant_admin(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> models.User:
    if _role_of(user, db) not in ("tenant_admin", "platform_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅商户管理员可访问")
    return user


def require_any_tenant_user(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> models.User:
    role = _role_of(user, db)
    if role == "platform_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请使用商户账号登录")
    return user
