"""口令哈希与访问令牌（决策 D15）：只用标准库，不引入 PyJWT/bcrypt。

- 口令：``hashlib.scrypt`` 加随机盐，参数随哈希一起存储（``scrypt$n$r$p$盐$摘要``），日后调参不影响旧口令校验；
- 令牌：标准 JWT 格式、HS256 签名（header.payload.signature，base64url 无填充）。
  校验时核对算法字段、签名（恒定时间比较）与过期时间，任何一项不符都视为无效令牌。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
DEV_SECRET = "agriscout-dev-secret-not-for-production"
MIN_PASSWORD_LENGTH = 8


class InvalidToken(ValueError):
    """令牌格式、签名或有效期不对。"""


# ---------- 口令 ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def check_password_strength(password: str) -> str | None:
    """返回不合格原因；合格返回 None。只做长度下限，不强制字符类别（口令短语同样安全）。"""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"口令至少 {MIN_PASSWORD_LENGTH} 位"
    return None


# ---------- 令牌 ----------
_dev_secret_warned = False


def signing_key() -> bytes:
    global _dev_secret_warned
    settings = get_settings()
    if settings.auth_secret:
        return settings.auth_secret.encode()
    if settings.environment != "dev":
        raise RuntimeError("非开发环境必须设置 AUTH_SECRET（令牌签名密钥）")
    if not _dev_secret_warned:  # 每个请求都会验签，只提醒一次
        logger.warning("AUTH_SECRET 未设置，使用开发密钥签发令牌——仅限本地开发")
        _dev_secret_warned = True
    return DEV_SECRET.encode()


def create_token(claims: dict[str, Any], ttl_seconds: int, *, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = {**claims, "iat": issued, "exp": issued + ttl_seconds}
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64(_json(header))}.{_b64(_json(payload))}"
    return f"{signing_input}.{_b64(_sign(signing_input))}"


def decode_token(token: str, *, now: float | None = None) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_unb64(header_b64))
        payload = json.loads(_unb64(payload_b64))
        signature = _unb64(signature_b64)
    except (ValueError, TypeError) as exc:
        raise InvalidToken("令牌格式不正确") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise InvalidToken("不支持的签名算法")
    if not hmac.compare_digest(signature, _sign(f"{header_b64}.{payload_b64}")):
        raise InvalidToken("令牌签名无效")
    if not isinstance(payload, dict) or not isinstance(payload.get("exp"), int):
        raise InvalidToken("令牌缺少有效期")
    if payload["exp"] <= int(now if now is not None else time.time()):
        raise InvalidToken("令牌已过期，请重新登录")
    return payload


def _sign(signing_input: str) -> bytes:
    return hmac.new(signing_key(), signing_input.encode(), hashlib.sha256).digest()


def _json(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
