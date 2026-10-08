"""逐点落盘（计划 0016 阶段 A4）：拍一张存一张，断电不丢已拍的点。

每趟巡检一个目录 ``<spool>/<patrol_uid>/``：
- ``meta.json``：包头（地块、种植、设备、开始时间），原子写入；
- ``photos/<seq>.jpg``：先写临时文件，fsync 后 rename；
- ``points.jsonl``：照片落盘之后再追加一行点记录，flush + fsync。

所以 ``points.jsonl`` 里的每一行都有对应照片；末尾写了一半的行在 ``resume()`` 时截掉。

拍完（或中断后）由 ``build_package()`` 组成协议 v2 的元数据包（计划 0016 阶段 B）：不读照片，点里只记本地
``photo_file``，上传时先逐张传照片再换成平台 URL，所以内存占用与照片数无关。组包进入上传队列后写 ``queued.json``
封存目录：照片留在这里直到平台确认收包，封存的目录不再算「未完成」。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .positioning import valid_key
except ImportError:  # 在 rover/ 目录下直接运行 python run.py
    from positioning import valid_key  # type: ignore[no-redef]

META_FILE = "meta.json"
POINTS_FILE = "points.jsonl"
PHOTO_DIR = "photos"
SEALED_FILE = "queued.json"
# 协议 v2 的视角字段（计划 0013「共同约定」）；本地记录里的其余字段（tags、reshoot_reason 等）不上传
VIEW_FIELDS = ("side", "pitch_deg", "yaw_deg", "height_m", "fill_light", "attempt", "accepted", "quality")
# 停车点级的位置字段：同一停车点拍的是同一株，读到标签的停车点统一取标签那一刻的结果
STOP_FIELDS = ("observation_key", "route_chainage_m", "position_source", "lng", "lat")


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
    def _trip_dirs(spool_dir: str | Path) -> list[Path]:
        root = Path(spool_dir)
        if not root.is_dir():
            return []
        return sorted(path for path in root.iterdir() if (path / META_FILE).is_file())

    @staticmethod
    def unfinished(spool_dir: str | Path) -> list[Path]:
        """列出还没组包的巡检目录（有 meta.json、未封存的子目录），按目录名排序。"""
        return [path for path in PointStore._trip_dirs(spool_dir) if not (path / SEALED_FILE).exists()]

    @staticmethod
    def sealed(spool_dir: str | Path) -> list[tuple[Path, str | None]]:
        """已组包封存的巡检目录及其队列包号（封存文件损坏时包号为 None）。"""
        result = []
        for path in PointStore._trip_dirs(spool_dir):
            marker = path / SEALED_FILE
            if not marker.exists():
                continue
            try:
                package_id = json.loads(marker.read_text(encoding="utf-8")).get("package_id")
            except (OSError, ValueError, AttributeError):
                package_id = None
            result.append((path, package_id if isinstance(package_id, str) else None))
        return result

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

    def build_package(self, client_package_id: str) -> dict[str, Any]:
        """组成协议 v2 的元数据包。照片不读进内存：有照片的点带本地 ``photo_file``，``photo`` 留空，
        上传时由 ``upload.wire_package`` 换成平台 URL。株号不合平台正则时不上传（留在本地 JSONL）。"""
        if not self._points:
            raise ValueError("本趟巡检没有任何点，无法组包")
        meta = self.meta
        tagged: dict[Any, dict[str, Any]] = {}
        for record in self._points:
            if record.get("position_source") == "tag":
                tagged.setdefault(record.get("stop"), record)
        capture_points: list[dict[str, Any]] = []
        track: list[list[float]] = []
        for record in self._points:
            where = tagged.get(record.get("stop"), record)
            key = where.get("observation_key")
            view = record.get("view")
            capture_points.append({
                "seq": record["seq"],
                "distance_m": record["distance_m"],
                "lng": where["lng"],
                "lat": where["lat"],
                "captured_at": record["captured_at"],
                "photo": None,
                "photo_file": record.get("photo_file"),
                "weather": None,
                "observation_key": key if valid_key(key) else None,
                "route_chainage_m": where.get("route_chainage_m"),
                "distance_source": record.get("distance_source"),
                "position_source": where.get("position_source"),
                "view": {k: view[k] for k in VIEW_FIELDS if k in view} if isinstance(view, dict) else None,
            })
            position = [where["lng"], where["lat"]]
            if not track or track[-1] != position:
                track.append(position)
        started = datetime.fromisoformat(meta["started_at"])
        ended = datetime.fromisoformat(self._points[-1]["captured_at"])
        if ended <= started:
            ended = started + timedelta(seconds=1)
        return {
            "schema_version": "2.0",
            "patrol": {
                "field_id": meta["field_id"],
                "planting_id": meta.get("planting_id"),
                "device": meta["device"],
                "started_at": meta["started_at"],
                "ended_at": ended.isoformat(),
                "track": track,
                "notes": meta.get("notes"),
                "client_package_id": client_package_id,
            },
            "capture_points": capture_points,
        }

    def seal(self, package_id: str) -> None:
        """组包进入上传队列后封存目录：照片留到平台确认收包，之后不再续拍、不再重复组包。"""
        _atomic_write(self.directory / SEALED_FILE, json.dumps({"package_id": package_id}).encode("utf-8"))

    def remove(self) -> None:
        """删除本地目录（一张都没拍就中断时；上传成功后由队列删除）。"""
        shutil.rmtree(self.directory, ignore_errors=True)
