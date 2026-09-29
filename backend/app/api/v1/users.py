"""用户管理（决策 D15）：仅管理员。不提供删除——停用即可，历史记录里的署名不会悬空。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, require_admin
from app.core.security import check_password_strength, hash_password
from app.models import User
from app.schemas.auth import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])


def _check_password(password: str) -> None:
    if problem := check_password_strength(password):
        raise HTTPException(status_code=422, detail=problem)


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.id)).all())


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    _check_password(payload.password)
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=409, detail=f"用户名已存在：{payload.username}")
    obj = User(username=payload.username, display_name=payload.display_name.strip(),
               password_hash=hash_password(payload.password), role=payload.role)
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户创建失败：用户名冲突")
    db.refresh(obj)
    return obj


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, current: CurrentUser = Depends(require_admin),
                db: Session = Depends(get_db)):
    obj = db.get(User, user_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    values = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if obj.id == current.id and (values.get("is_active") is False or values.get("role", "admin") != "admin"):
        raise HTTPException(status_code=409, detail="不能停用自己或取消自己的管理员身份")
    losing_admin = obj.role == "admin" and obj.is_active and (
        values.get("is_active") is False or values.get("role", "admin") != "admin")
    if losing_admin:
        admins = db.scalar(select(func.count()).select_from(User)
                           .where(User.role == "admin", User.is_active.is_(True)))
        if admins <= 1:
            raise HTTPException(status_code=409, detail="至少保留一个启用的管理员")
    if (password := values.pop("password", None)) is not None:
        _check_password(password)
        obj.password_hash = hash_password(password)
    for key, value in values.items():
        setattr(obj, key, value.strip() if key == "display_name" else value)
    db.commit()
    db.refresh(obj)
    return obj
