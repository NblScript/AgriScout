"""登录、当前用户、修改口令（决策 D15）。登录是除健康检查外唯一的公开接口。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.security import check_password_strength, create_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginIn, PasswordChangeIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# 用户名不存在时也跑一次 scrypt，避免用响应时间探测哪些用户名存在
_DUMMY_HASH = hash_password("agriscout-timing-guard")


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    valid = verify_password(payload.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not valid or not user.is_active:
        raise HTTPException(status_code=401, detail="用户名或口令错误，或账号已停用")
    now = datetime.now(timezone.utc)
    ttl = get_settings().auth_token_hours * 3600
    token = create_token({"sub": str(user.id), "username": user.username, "role": user.role},
                         ttl, now=now.timestamp())
    user.last_login_at = now
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=token, expires_at=now + timedelta(seconds=ttl), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.get(User, current.id)


@router.post("/change-password", status_code=204)
def change_password(payload: PasswordChangeIn, current: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    user = db.get(User, current.id)
    if user is None or not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原口令不正确")
    if problem := check_password_strength(payload.new_password):
        raise HTTPException(status_code=422, detail=problem)
    user.password_hash = hash_password(payload.new_password)
    db.commit()
