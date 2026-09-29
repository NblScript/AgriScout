"""命令行建号 / 重置口令（决策 D15）：平台没有默认账号，第一个管理员从这里建。

用法：
    cd backend && .venv/bin/python -m app.tools.create_user --username admin --role admin --name 管理员
    cd backend && .venv/bin/python -m app.tools.create_user --username sim --role operator --reset   # 已存在则重置口令
口令交互输入（不回显）；脚本化时用 --password-env 指定从哪个环境变量读取，避免口令出现在命令行历史里。
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import check_password_strength, hash_password
from app.models import User
from app.models.user import USER_ROLES


def _read_password(env_name: str | None) -> str:
    if env_name:
        value = os.environ.get(env_name, "")
        if not value:
            raise SystemExit(f"环境变量 {env_name} 为空")
        return value
    first = getpass.getpass("口令：")
    if first != getpass.getpass("再输一次："):
        raise SystemExit("两次输入不一致")
    return first


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="创建平台用户或重置口令")
    ap.add_argument("--username", required=True)
    ap.add_argument("--name", default=None, help="显示姓名（缺省同用户名）")
    ap.add_argument("--role", choices=USER_ROLES, default="operator")
    ap.add_argument("--reset", action="store_true", help="用户已存在时重置口令并按参数更新角色、启用账号")
    ap.add_argument("--password-env", default=None, help="从该环境变量读取口令（不交互）")
    args = ap.parse_args(argv)

    password = _read_password(args.password_env)
    if problem := check_password_strength(password):
        print(f"✗ {problem}")
        return 2
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is not None and not args.reset:
            print(f"✗ 用户 {args.username} 已存在（重置口令请加 --reset）")
            return 1
        if user is None:
            user = User(username=args.username, display_name=args.name or args.username,
                        password_hash=hash_password(password), role=args.role)
            db.add(user)
            action = "已创建"
        else:
            user.password_hash = hash_password(password)
            user.role = args.role
            user.is_active = True
            if args.name:
                user.display_name = args.name
            action = "已重置"
        db.commit()
        print(f"✓ {action}用户 {user.username}（{user.display_name}，角色 {user.role}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
