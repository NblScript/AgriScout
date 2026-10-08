"""照片分步上传（计划 0016 阶段 B2）：先逐张查重、上传照片，再提交只含 URL 的 v2 元数据包。

一次只读一张照片进内存，整趟 2600 张也不会撑爆树莓派的内存。平台按内容 SHA-256 寻址，
已有的照片（上次传到一半断网、或补拍到同一张图）只查不传；同一份字节的 URL 永远相同，
所以重传的元数据包内容不变，平台按包号判为重复补传（200 + duplicate）。
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

PNG_MAGIC = b"\x89PNG"


def content_type_of(data: bytes) -> str:
    return "image/png" if data[:4] == PNG_MAGIC else "image/jpeg"


def photo_path(root: Path, relative: str) -> Path:
    """队列包里的 ``photo_file`` 只能指向本趟目录里的文件（防止被改过的队列文件读到别处）。"""
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"照片路径越出巡检目录：{relative}")
    return path


def upload_photos(
    client: Any,
    root: Path,
    package: dict[str, Any],
    *,
    call: Callable[[Callable[[], Any]], Any] = lambda fn: fn(),
) -> tuple[dict[int, str], int]:
    """逐张查重并上传；返回 ({seq: 平台 URL}, 本次新传张数)。``call`` 包一层重试。"""
    urls: dict[int, str] = {}
    uploaded = 0
    for point in package["capture_points"]:
        relative = point.get("photo_file")
        if not relative:
            continue
        data = photo_path(root, relative).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        found = call(lambda: client.media_exists(digest))
        url = found.get("url") if found.get("exists") else None
        if not url:
            url = call(lambda: client.upload_media(data, content_type_of(data)))["url"]
            uploaded += 1
        urls[point["seq"]] = url
    return urls, uploaded


def wire_package(package: dict[str, Any], urls: dict[int, str]) -> dict[str, Any]:
    """队列里的元数据包 → 发给平台的包：``photo_file`` 换成平台 URL，本地字段不上传。"""
    points = []
    for point in package["capture_points"]:
        wire = {key: value for key, value in point.items() if key != "photo_file"}
        if point.get("photo_file"):
            wire["photo"] = urls[point["seq"]]
        points.append(wire)
    return {**package, "capture_points": points}
