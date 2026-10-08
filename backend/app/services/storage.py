"""照片存储抽象（基线 D6）：本地目录实现，生产换对象存储只改此处。"""
import hashlib
import uuid
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

# 允许的扩展名白名单；按 SHA-256 查找时按此顺序试（上传只会产出 .jpg / .png）
_LOOKUP_ORDER = (".jpg", ".png", ".jpeg", ".webp")
_SUFFIXES = set(_LOOKUP_ORDER)


def photo_suffix(data: bytes) -> str:
    """按文件魔数定扩展名：PNG 魔数 → .png，其余一律 .jpg。

    巡检包 base64 照片与 ``POST /media`` 共用同一规则，同一份字节无论走哪条路都得到同一个 URL。
    """
    return ".png" if data[:4] == b"\x89PNG" else ".jpg"


class Storage(Protocol):
    """照片存储接口：写入二进制返回 URL；按 URL 读回字节（分析管线用）。"""

    def save(self, data: bytes, suffix: str = ".jpg") -> str: ...

    def save_tracked(self, data: bytes, suffix: str = ".jpg") -> tuple[str, bool]:
        """同 save，额外返回本次是否新建了文件。

        内容寻址天然去重：同图已存在时不会重写，返回 False——调用方回滚清理时
        只能删除自己新建的文件，否则会误删其他巡检仍在引用的共享照片。
        """
        ...

    def open(self, url: str) -> bytes | None:
        """读回照片字节；非本地引用或文件缺失返回 None（调用方自行跳过）。"""
        ...

    def exists(self, url: str) -> bool:
        """``/media/`` 引用对应的文件是否存在（巡检包接入校验用，不读内容）。"""
        ...

    def find(self, sha256: str) -> str | None:
        """按内容 SHA-256（小写十六进制）找已存的照片，返回 URL；没有返回 None。"""
        ...

    def delete(self, url: str) -> None:
        """删除照片文件（落库失败时的孤儿清理用）；文件不存在则静默。"""
        ...


class LocalStorage:
    """本地目录存储：内容 SHA-256 寻址，天然去重（同图只存一份）。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, data: bytes, suffix: str = ".jpg") -> str:
        return self.save_tracked(data, suffix)[0]

    def save_tracked(self, data: bytes, suffix: str = ".jpg") -> tuple[str, bool]:
        suffix = suffix.lower()
        if suffix not in _SUFFIXES:
            suffix = ".jpg"
        digest = hashlib.sha256(data).hexdigest()
        name = f"{digest}{suffix}"
        path = self.root / name
        created = False
        if not path.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再原子改名，避免并发半截文件；临时名带随机后缀，
            # 防止两个请求同时写同一张图时互相覆盖临时文件
            tmp = path.with_name(f"{name}.{uuid.uuid4().hex}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            created = True
        return f"/media/{name}", created

    def _local_path(self, url: str) -> Path | None:
        """``/media/<名>`` → 本地路径；外部 URL 或可疑名字（防路径穿越）返回 None。"""
        if not url or not url.startswith("/media/"):
            return None
        name = url.removeprefix("/media/")
        if not name or "/" in name or "\\" in name or ".." in name:
            return None
        return self.root / name

    def open(self, url: str) -> bytes | None:
        path = self._local_path(url)
        if path is None:
            return None  # 外部 URL 不在本地，占位管线不联网抓取
        try:
            return path.read_bytes()
        except OSError:
            return None

    def exists(self, url: str) -> bool:
        path = self._local_path(url)
        return path is not None and path.is_file()

    def find(self, sha256: str) -> str | None:
        digest = sha256.lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            return None
        for suffix in _LOOKUP_ORDER:
            if (self.root / f"{digest}{suffix}").is_file():
                return f"/media/{digest}{suffix}"
        return None

    def delete(self, url: str) -> None:
        path = self._local_path(url)
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def get_storage() -> Storage:
    """FastAPI 依赖：测试可 dependency_overrides 换临时目录。"""
    return LocalStorage(get_settings().media_dir)
