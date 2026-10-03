"""逐点落盘（计划 0016 阶段 A4）：拍一张存一张，断电不丢已拍的点。

每趟巡检一个目录 ``<spool>/<patrol_uid>/``：
- ``meta.json``：包头（地块、种植、设备、开始时间），原子写入；
- ``photos/<seq>.jpg``：先写临时文件，fsync 后 rename；
- ``points.jsonl``：照片落盘之后再追加一行点记录，flush + fsync。

所以 ``points.jsonl`` 里的每一行都有对应照片；末尾写了一半的行在 ``resume()`` 时截掉。
阶段 A 仍由 ``build_package()`` 逐张读回照片组成 base64 的 v1 包，交给 ``PackageSpool``。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

META_FILE = "meta.json"
POINTS_FILE = "points.jsonl"
PHOTO_DIR = "photos"


def _fsync_dir(directory: Path) -> None:
    # 目录 fsync 让 rename 本身落盘；部分平台（Windows）不支持，忽略即可
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(target: Path, data: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    _fsync_dir(target.parent)


class PointStore:
    """一趟巡检的本地点记录。``seq`` 由本类按追加顺序分配，从 0 开始连续。"""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self._points: list[dict[str, Any]] = []

    # ---------------------------------------------------------- 建立与恢复

    @classmethod
    def create(cls, spool_dir: str | Path, patrol_uid: str, meta: dict[str, Any]) -> "PointStore":
        directory = Path(spool_dir) / patrol_uid
        if (directory / META_FILE).exists():
            raise FileExistsError(f"巡检目录已存在：{directory}")
        (directory / PHOTO_DIR).mkdir(parents=True, exist_ok=True)
        _atomic_write(directory / META_FILE, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        return cls(directory)

    @staticmethod
    def unfinished(spool_dir: str | Path) -> list[Path]:
        """列出还没组包的巡检目录（有 meta.json 的子目录），按目录名排序。"""
        root = Path(spool_dir)
        if not root.is_dir():
            return []
        return sorted(path for path in root.iterdir() if (path / META_FILE).is_file())

    @property
    def meta(self) -> dict[str, Any]:
        return json.loads((self.directory / META_FILE).read_text(encoding="utf-8"))

    @property
    def points(self) -> list[dict[str, Any]]:
        return list(self._points)

    @property
    def next_seq(self) -> int:
        return len(self._points)

    def resume(self) -> list[dict[str, Any]]:
        """读回已落盘的点；末尾写了一半的行被截掉，之后的追加从下一个 seq 继续。"""
        path = self.directory / POINTS_FILE
        self._points = []
        if not path.exists():
            return []
        raw = path.read_bytes()
        good_end = 0
        offset = 0
        for line in raw.splitlines(keepends=True):
            offset += len(line)
            if not line.endswith(b"\n"):
                break  # 末尾没写完的行
            try:
                record = json.loads(line)
            except ValueError:
                break  # 行内容残缺：之后的内容都不可信
            if not isinstance(record, dict) or record.get("seq") != len(self._points):
                break
            self._points.append(record)
            good_end = offset
        if good_end != len(raw):
            with path.open("r+b") as handle:
                handle.truncate(good_end)
                handle.flush()
                os.fsync(handle.fileno())
        return self.points

    # ---------------------------------------------------------- 写入

    def append(self, point: dict[str, Any], photo: bytes | None) -> dict[str, Any]:
        """先落照片、再追加点记录；返回带 ``seq`` 和 ``photo_file`` 的记录。"""
        seq = self.next_seq
        record = {**point, "seq": seq, "photo_file": None}
        if photo is not None:
            relative = f"{PHOTO_DIR}/{seq}.jpg"
            _atomic_write(self.directory / relative, photo)
            record["photo_file"] = relative
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with (self.directory / POINTS_FILE).open("ab") as handle:
            handle.write(line.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        self._points.append(record)
        return record

    # ---------------------------------------------------------- 组包

    def build_package(self) -> dict[str, Any]:
        """逐张读回照片，组成巡检包 v1。

        株号、行内位置、视角等字段阶段 A 只留在本地 JSONL，阶段 B 才随协议 v2 上传。
        """
        if not self._points:
            raise ValueError("本趟巡检没有任何点，无法组包")
        meta = self.meta
        capture_points: list[dict[str, Any]] = []
        track: list[list[float]] = []
        for record in self._points:
            photo_b64 = None
            if record.get("photo_file"):
                photo_b64 = base64.b64encode(
                    (self.directory / record["photo_file"]).read_bytes(),
                ).decode("ascii")
            capture_points.append({
                "seq": record["seq"],
                "distance_m": record["distance_m"],
                "lng": record["lng"],
                "lat": record["lat"],
                "captured_at": record["captured_at"],
                "photo": photo_b64,
                "weather": None,
            })
            position = [record["lng"], record["lat"]]
            if not track or track[-1] != position:
                track.append(position)
        started = datetime.fromisoformat(meta["started_at"])
        ended = datetime.fromisoformat(self._points[-1]["captured_at"])
        if ended <= started:
            ended = started + timedelta(seconds=1)
        return {
            "patrol": {
                "field_id": meta["field_id"],
                "planting_id": meta.get("planting_id"),
                "device": meta["device"],
                "started_at": meta["started_at"],
                "ended_at": ended.isoformat(),
                "track": track,
                "notes": meta.get("notes"),
            },
            "capture_points": capture_points,
        }

    def remove(self) -> None:
        """组包并进入上传队列后删除本地目录（照片已在队列包里）。"""
        shutil.rmtree(self.directory, ignore_errors=True)
