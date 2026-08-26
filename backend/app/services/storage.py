"""照片存储抽象（基线 D6）：本地目录实现，生产换对象存储只改此处。"""
import hashlib
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

# 允许的扩展名白名单
_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class Storage(Protocol):
    """照片存储接口：写入二进制，返回可直接访问的 URL。"""

    def save(self, data: bytes, suffix: str = ".jpg") -> str: ...


class LocalStorage:
    """本地目录存储：内容 SHA-256 寻址，天然去重（同图只存一份）。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, data: bytes, suffix: str = ".jpg") -> str:
        suffix = suffix.lower()
        if suffix not in _SUFFIXES:
            suffix = ".jpg"
        digest = hashlib.sha256(data).hexdigest()
        name = f"{digest}{suffix}"
        path = self.root / name
        if not path.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再原子改名，避免并发半截文件
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return f"/media/{name}"


def get_storage() -> Storage:
    """FastAPI 依赖：测试可 dependency_overrides 换临时目录。"""
    return LocalStorage(get_settings().media_dir)
