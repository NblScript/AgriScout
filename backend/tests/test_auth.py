"""登录认证与角色权限（决策 D15）：令牌、公开白名单、只读账号、用户管理、全路由挂依赖。"""
import re

import pytest

from app.core import security
from app.core.deps import API_PREFIX, PUBLIC_ENDPOINTS
from app.core.security import InvalidToken, create_token, decode_token, hash_password, verify_password
from app.models import User

PASSWORD = "correct-horse-9"


def _add_user(session_factory, username: str, role: str = "operator", *, active: bool = True) -> int:
    with session_factory() as db:
        user = User(username=username, display_name=f"{username} 姓名", password_hash=hash_password(PASSWORD),
                    role=role, is_active=active)
        db.add(user)
        db.commit()
        return user.id


def _login(client, username: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _headers(client, username: str) -> dict[str, str]:
    resp = _login(client, username)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------- 口令与令牌（纯函数） ----------
def test_password_hash_roundtrip_and_salted():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second  # 随机盐
    assert first.startswith("scrypt$") and PASSWORD not in first
    assert verify_password(PASSWORD, first) and not verify_password("wrong-pass-1", first)
    assert not verify_password(PASSWORD, "garbage") and not verify_password(PASSWORD, "bcrypt$1$2$3$4$5")


def test_token_roundtrip_expiry_and_tamper():
    token = create_token({"sub": "7"}, 60, now=1_000_000)
    assert decode_token(token, now=1_000_030)["sub"] == "7"
    with pytest.raises(InvalidToken, match="过期"):
        decode_token(token, now=1_000_060)
    header, payload, signature = token.split(".")
    forged = create_token({"sub": "1"}, 60, now=1_000_000).split(".")[1]
    with pytest.raises(InvalidToken, match="签名"):
        decode_token(f"{header}.{forged}.{signature}", now=1_000_030)
    none_header = security._b64(b'{"alg":"none","typ":"JWT"}')
    with pytest.raises(InvalidToken, match="算法"):
        decode_token(f"{none_header}.{payload}.", now=1_000_030)
    with pytest.raises(InvalidToken):
        decode_token("not-a-token")


def test_token_signed_with_other_secret_rejected(monkeypatch):
    token = create_token({"sub": "7"}, 60)
    monkeypatch.setattr(security, "signing_key", lambda: b"another-secret")
    with pytest.raises(InvalidToken, match="签名"):
        decode_token(token)


# ---------- 公开白名单与 401 ----------
def test_health_and_login_are_public_everything_else_requires_token(auth_env):
    client, _ = auth_env
    assert client.get("/api/v1/health").status_code == 200
    resp = client.get("/api/v1/fields")
    assert resp.status_code == 401 and resp.headers["WWW-Authenticate"] == "Bearer"
    assert client.get("/api/v1/fields", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/v1/fields", headers={"Authorization": "Basic abc"}).status_code == 401


def test_login_success_updates_last_login(auth_env):
    client, sessions = auth_env
    _add_user(sessions, "alice")
    resp = _login(client, "alice")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer" and body["user"]["username"] == "alice"
    assert "password_hash" not in body["user"] and body["user"]["last_login_at"] is not None
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["role"] == "operator"


@pytest.mark.parametrize("username,password", [("alice", "wrong-password"), ("nobody", PASSWORD)])
def test_login_failure_is_generic(auth_env, username, password):
    client, sessions = auth_env
    _add_user(sessions, "alice")
    resp = _login(client, username, password)
    assert resp.status_code == 401 and resp.json()["detail"] == "用户名或口令错误，或账号已停用"


def test_disabled_user_cannot_login_and_existing_token_stops_working(auth_env):
    client, sessions = auth_env
    admin_headers = _headers(client, "boss") if _add_user(sessions, "boss", "admin") else None
    bob_id = _add_user(sessions, "bob")
    bob_headers = _headers(client, "bob")
    assert client.get("/api/v1/fields", headers=bob_headers).status_code == 200
    assert client.patch(f"/api/v1/users/{bob_id}", json={"is_active": False}, headers=admin_headers).status_code == 200
    assert client.get("/api/v1/fields", headers=bob_headers).status_code == 401
    assert _login(client, "bob").status_code == 401


# ---------- 角色 ----------
def test_viewer_is_read_only_but_can_change_own_password(auth_env):
    client, sessions = auth_env
    _add_user(sessions, "val", "viewer")
    headers = _headers(client, "val")
    assert client.get("/api/v1/fields", headers=headers).status_code == 200
    resp = client.post("/api/v1/crops", json={"name": "小麦", "lifecycle_days": 240, "stages": []}, headers=headers)
    assert resp.status_code == 403 and resp.json()["detail"] == "只读账号不能修改数据"
    changed = client.post("/api/v1/auth/change-password",
                          json={"old_password": PASSWORD, "new_password": "new-secret-42"}, headers=headers)
    assert changed.status_code == 204
    assert _login(client, "val", "new-secret-42").status_code == 200


def test_change_password_checks_old_and_strength(auth_env):
    client, sessions = auth_env
    _add_user(sessions, "carl")
    headers = _headers(client, "carl")
    wrong = client.post("/api/v1/auth/change-password", json={"old_password": "bad", "new_password": "long-enough-1"},
                        headers=headers)
    assert wrong.status_code == 400
    short = client.post("/api/v1/auth/change-password", json={"old_password": PASSWORD, "new_password": "short"},
                        headers=headers)
    assert short.status_code == 422


def test_operator_can_write_business_data_but_not_manage_users(auth_env):
    client, sessions = auth_env
    _add_user(sessions, "olga")
    headers = _headers(client, "olga")
    created = client.post("/api/v1/crops", json={"name": "小麦", "lifecycle_days": 240, "stages": []}, headers=headers)
    assert created.status_code == 201
    assert client.get("/api/v1/users", headers=headers).status_code == 403
    new_user = {"username": "eve", "display_name": "Eve", "password": "long-enough-1", "role": "admin"}
    assert client.post("/api/v1/users", json=new_user, headers=headers).status_code == 403


def test_admin_manages_users(auth_env):
    client, sessions = auth_env
    _add_user(sessions, "root", "admin")
    headers = _headers(client, "root")
    payload = {"username": "new.user", "display_name": "新同学", "password": "long-enough-1", "role": "viewer"}
    created = client.post("/api/v1/users", json=payload, headers=headers)
    assert created.status_code == 201 and created.json()["role"] == "viewer"
    assert client.post("/api/v1/users", json=payload, headers=headers).status_code == 409
    weak = {**payload, "username": "weak", "password": "123"}
    assert client.post("/api/v1/users", json=weak, headers=headers).status_code == 422
    user_id = created.json()["id"]
    updated = client.patch(f"/api/v1/users/{user_id}", json={"role": "operator", "password": "reset-pass-99"},
                           headers=headers)
    assert updated.status_code == 200 and updated.json()["role"] == "operator"
    assert _login(client, "new.user", "reset-pass-99").status_code == 200
    listed = client.get("/api/v1/users", headers=headers).json()
    assert [u["username"] for u in listed] == ["root", "new.user"]


def test_last_active_admin_is_protected(auth_env):
    client, sessions = auth_env
    root_id = _add_user(sessions, "root", "admin")
    other_id = _add_user(sessions, "other", "admin")
    headers = _headers(client, "root")
    # 不能停用或降级自己
    assert client.patch(f"/api/v1/users/{root_id}", json={"is_active": False}, headers=headers).status_code == 409
    assert client.patch(f"/api/v1/users/{root_id}", json={"role": "viewer"}, headers=headers).status_code == 409
    # 还有别的管理员时可以降级对方，之后自己就是最后一个
    assert client.patch(f"/api/v1/users/{other_id}", json={"role": "operator"}, headers=headers).status_code == 200
    assert client.patch(f"/api/v1/users/{other_id}", json={"role": "admin"}, headers=headers).status_code == 200


def test_last_admin_cannot_be_disabled_by_another_admin_race(auth_env):
    """两个管理员互相停用：第二次必须被拒，保证系统里始终有启用的管理员。"""
    client, sessions = auth_env
    a_id = _add_user(sessions, "a-admin", "admin")
    b_id = _add_user(sessions, "b-admin", "admin")
    a_headers, b_headers = _headers(client, "a-admin"), _headers(client, "b-admin")
    assert client.patch(f"/api/v1/users/{b_id}", json={"is_active": False}, headers=a_headers).status_code == 200
    assert client.patch(f"/api/v1/users/{a_id}", json={"is_active": False}, headers=b_headers).status_code == 401


# ---------- 红线 5：全路由挂认证依赖 ----------
def test_every_api_endpoint_rejects_anonymous_requests(auth_env):
    """按 OpenAPI 列出的全部接口逐个匿名调用：除白名单外必须 401（行为层面锁住「不得绕过」）。"""
    client, _ = auth_env
    public = {(m, p.removeprefix(API_PREFIX)) for m, p in PUBLIC_ENDPOINTS}
    paths = client.app.openapi()["paths"]
    checked, leaked = 0, []
    for path, operations in paths.items():
        for method in operations:
            method = method.upper()
            if (method, path.removeprefix(API_PREFIX)) in public:
                continue
            url = re.sub(r"\{[^}]+\}", "1", path)
            status = client.request(method, url).status_code
            checked += 1
            if status != 401:
                leaked.append(f"{method} {path} -> {status}")
    assert checked > 50 and leaked == []


def test_create_user_tool(monkeypatch, auth_env, capsys):
    from app.tools import create_user

    client, sessions = auth_env
    monkeypatch.setattr(create_user, "SessionLocal", sessions)
    monkeypatch.setenv("BOOT_PW", "bootstrap-pass-1")
    assert create_user.main(["--username", "admin", "--role", "admin", "--name", "管理员",
                             "--password-env", "BOOT_PW"]) == 0
    assert create_user.main(["--username", "admin", "--password-env", "BOOT_PW"]) == 1
    monkeypatch.setenv("BOOT_PW", "short")
    assert create_user.main(["--username", "x", "--password-env", "BOOT_PW"]) == 2
    assert _login(client, "admin", "bootstrap-pass-1").json()["user"]["display_name"] == "管理员"
    assert "已创建用户 admin" in capsys.readouterr().out
