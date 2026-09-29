"""通用依赖：认证插槽（基线 B4 → 决策 D15）。

所有业务路由在 ``api_router`` 层统一挂 ``get_current_user``；访问策略集中在这一处：
- 公开：健康检查、登录（其余一律要 ``Authorization: Bearer <令牌>``）；
- 每次请求回库读取用户：停用或改角色立即生效，不必等令牌过期；
- viewer 只读：非 GET/HEAD/OPTIONS 请求 403；用户管理另由 ``require_admin`` 把关。
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import InvalidToken, decode_token

API_PREFIX = "/api/v1"
PUBLIC_ENDPOINTS = {("GET", f"{API_PREFIX}/health"), ("POST", f"{API_PREFIX}/auth/login")}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# 只读账号也允许的写操作：只动自己账号的自助接口
SELF_SERVICE_ENDPOINTS = {("POST", f"{API_PREFIX}/auth/change-password")}


@dataclass(frozen=True)
class CurrentUser:
    id: int | None
    username: str
    display_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


ANONYMOUS = CurrentUser(id=None, username="anonymous", display_name="匿名", role="anonymous")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    from app.models.user import User  # 延迟导入：core 不在导入期依赖 models

    endpoint = (request.method, request.url.path.rstrip("/"))
    if endpoint in PUBLIC_ENDPOINTS:
        return ANONYMOUS
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("请先登录")
    try:
        claims = decode_token(token.strip())
    except InvalidToken as exc:
        raise _unauthorized(str(exc)) from exc
    user_id = claims.get("sub")
    user = db.get(User, int(user_id)) if isinstance(user_id, str) and user_id.isdigit() else None
    if user is None or not user.is_active:
        raise _unauthorized("账号不存在或已停用")
    if user.role == "viewer" and request.method not in SAFE_METHODS and endpoint not in SELF_SERVICE_ENDPOINTS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只读账号不能修改数据")
    return CurrentUser(id=user.id, username=user.username, display_name=user.display_name, role=user.role)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user
