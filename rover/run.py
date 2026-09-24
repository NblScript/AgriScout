"""AgriScout 真车采集端（树莓派 + USB 摄像头）。

采集端只依赖巡检包 HTTP 协议：建档 → 采集 → 组包 → 上传。
没有摄像头时使用 ``--fake`` 验证完整链路；接入编码器、GPS、传感器时，
只需替换对应的采集源，不需要修改平台后端。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

TZ_CN = timezone(timedelta(hours=8))
WHEAT_STAGES = [
    {"name": "出苗期", "days": 15},
    {"name": "分蘖期", "days": 30},
    {"name": "拔节期", "days": 25},
    {"name": "抽穗期", "days": 20},
    {"name": "灌浆期", "days": 35},
    {"name": "成熟期", "days": 115},
]


class CaptureSource(Protocol):
    def capture(self) -> bytes: ...
    def close(self) -> None: ...


class ApiError(RuntimeError):
    """HTTP/transport error with enough context for safe retry decisions."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class PackageSpool:
    """Crash-safe local queue for complete patrol packages.

    A package is written to a temporary file and atomically renamed before an
    upload is attempted.  The queue contains the exact HTTP payload so a
    retry never re-captures images or changes their timestamps.
    """

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def package_id(package: dict[str, Any]) -> str:
        header = package["patrol"]
        identity = "|".join(
            str(header.get(key, ""))
            for key in ("device", "field_id", "started_at")
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    def path_for(self, package: dict[str, Any]) -> Path:
        return self.directory / f"{self.package_id(package)}.json"

    def save(self, package: dict[str, Any], *, last_error: str | None = None) -> Path:
        target = self.path_for(package)
        envelope = {
            "package": package,
            "package_id": self.package_id(package),
            "attempts": 0,
            "last_error": last_error,
            "queued_at": datetime.now(TZ_CN).isoformat(),
        }
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.stem}.", suffix=".tmp", dir=self.directory,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(envelope, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        return target

    def pending(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"))

    @staticmethod
    def read(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            envelope = json.load(handle)
        if "package" not in envelope or not isinstance(envelope["package"], dict):
            raise ValueError("队列文件缺少 package 对象")
        return envelope["package"], envelope

    def record_failure(self, path: Path, envelope: dict[str, Any], error: str) -> None:
        current = dict(envelope)
        current["attempts"] = int(envelope.get("attempts", 0)) + 1
        current["last_error"] = error
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=self.directory,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(current, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def remove(self, path: Path) -> None:
        path.unlink(missing_ok=True)


class ApiClient(AbstractContextManager["ApiClient"]):
    """平台 HTTP 客户端（只走 HTTP，不 import 后端内部代码）。"""

    def __init__(self, base_url: str, timeout: float = 120.0):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("--api 必须是 http:// 或 https:// 地址")
        self.base_url = base_url.rstrip("/")
        # 巡检端通常访问局域网内的后端；不继承主机代理，避免 SOCKS
        # 环境变量把本地请求导向未安装 socksio 的代理适配器。
        self._c = httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False)

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._c.close()

    def _req(self, method: str, path: str, json_body: Any = None, expect=(200, 201)):
        try:
            resp = self._c.request(method, path, json=json_body)
        except httpx.RequestError as exc:
            raise ApiError(
                f"{method} {path} 网络请求失败：{exc}", retryable=True,
            ) from exc
        if resp.status_code not in expect:
            detail = resp.text.replace("\n", " ")[:300]
            raise ApiError(
                f"{method} {path} -> HTTP {resp.status_code}: {detail}",
                status_code=resp.status_code,
                retryable=resp.status_code in {408, 425, 429, 500, 502, 503, 504},
            )
        if method == "DELETE" or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError(f"{method} {path} 返回了非 JSON 响应") from exc

    def get(self, path: str):
        return self._req("GET", path)

    def post(self, path: str, body: Any, expect=(200, 201)):
        return self._req("POST", path, json_body=body, expect=expect)

    def ensure_device(self, code: str, name: str, model: str = "Robot-Eye Rover"):
        for device in self.get("/api/v1/devices"):
            if device["code"] == code:
                return device
        return self.post("/api/v1/devices", {
            "code": code, "name": name, "type": "rover", "model": model,
        })

    def register_device(self, code: str, name: str, model: str = "Robot-Eye Rover") -> dict[str, Any]:
        """按 code 幂等注册小车，返回平台分配的设备 id。"""
        return self.post("/api/v1/devices/register", {
            "code": code, "name": name, "type": "rover", "model": model,
        }, expect=(200,))

    def send_heartbeat(self, device_id: int, heartbeat: dict[str, Any]) -> dict[str, Any]:
        """上报设备自检/任务阶段；硬件观测字段由调用方真实提供。"""
        return self.post(f"/api/v1/devices/{device_id}/heartbeat", heartbeat, expect=(200,))

    def report_event(self, device_id: int, event: dict[str, Any]) -> dict[str, Any]:
        """记录设备事件；client_event_id 可用于重发幂等。"""
        return self.post(f"/api/v1/devices/{device_id}/events", event, expect=(201,))

    def report_mission_event(self, mission_id: int, event: dict[str, Any]) -> dict[str, Any]:
        """记录任务事件；现阶段平台以 Patrol id 承载 mission_id。"""
        return self.post(f"/api/v1/missions/{mission_id}/events", event, expect=(201,))

    def next_task(self, device_id: int) -> dict[str, Any] | None:
        """领取下一条复巡任务；无任务时服务端返回 JSON null。"""
        return self.get(f"/api/v1/devices/{device_id}/tasks/next")

    def report_task_status(
        self, task_id: int, status: str, *, result_note: str | None = None,
    ) -> dict[str, Any]:
        """回报任务状态；设备控制动作仍由车端安全控制器执行。"""
        body: dict[str, Any] = {"status": status}
        if result_note is not None:
            body["result_note"] = result_note
        return self._req("PATCH", f"/api/v1/revisit-tasks/{task_id}", json_body=body, expect=(200,))

    def ensure_field(self, name: str, boundary: dict[str, Any]):
        for field in self.get("/api/v1/fields"):
            if field["name"] == name:
                return field
        return self.post("/api/v1/fields", {
            "name": name, "boundary": boundary, "soil_type": "壤土",
        })

    def ensure_crop(self, name: str, variety: str, lifecycle_days: int, stages: list[dict]):
        for crop in self.get("/api/v1/crops"):
            if crop["name"] == name:
                return crop
        return self.post("/api/v1/crops", {
            "name": name, "variety": variety,
            "lifecycle_days": lifecycle_days, "stages": stages,
        })

    def ensure_planting(self, field_id: int, crop_id: int, sowing_date: str):
        path = f"/api/v1/plantings?field_id={field_id}&status=active"
        for planting in self.get(path):
            if planting["crop_id"] == crop_id and planting["sowing_date"] == sowing_date:
                return planting
        return self.post("/api/v1/plantings", {
            "field_id": field_id, "crop_id": crop_id, "sowing_date": sowing_date,
        })

    def ingest(self, package: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/v1/ingest/patrol", package, expect=(201,))


def upload_with_retry(
    client: ApiClient,
    package: dict[str, Any],
    *,
    retries: int,
    retry_delay: float = 0.5,
    sleeper: Callable[[float], None] = time.sleep,
    package_id: str = "",
) -> dict[str, Any]:
    """Upload without changing the package; retry only transient failures."""
    attempts = max(0, retries) + 1
    for attempt in range(1, attempts + 1):
        try:
            return client.ingest(package)
        except RuntimeError as exc:
            # A 409 is not treated as success until the backend exposes a
            # stable client package id and a matching replay lookup.
            if isinstance(exc, ApiError) and exc.status_code == 409:
                raise
            retryable = getattr(exc, "retryable", True)
            if not retryable or attempt >= attempts:
                raise
            delay = min(30.0, retry_delay * (2 ** (attempt - 1)))
            print(
                f"[重试] package={package_id or 'unknown'} attempt={attempt + 1}/{attempts} "
                f"等待 {delay:g}s：{exc}",
            )
            sleeper(delay)
    raise AssertionError("unreachable")


def flush_spool(
    client: ApiClient,
    spool: PackageSpool,
    *,
    retries: int,
    retry_delay: float = 0.5,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[int, int]:
    """Replay pending packages; return ``(sent, failed)``."""
    sent = failed = 0
    for path in spool.pending():
        envelope: dict[str, Any] | None = None
        try:
            package, envelope = spool.read(path)
            package_id = envelope.get("package_id", spool.package_id(package))
            upload_with_retry(
                client, package, retries=retries, retry_delay=retry_delay,
                sleeper=sleeper, package_id=package_id,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            failed += 1
            if envelope is not None:
                try:
                    spool.record_failure(path, envelope, str(exc))
                except (OSError, ValueError, KeyError):
                    pass
            print(f"[队列] 暂未上传 {path.name}：{exc}")
            continue
        spool.remove(path)
        sent += 1
        print(f"[队列] 已补传 {path.name}")
    return sent, failed


class FakeCapture:
    """生成轻量合成图，用于无摄像头的链路验收。"""

    def __init__(self, width: int, height: int):
        from PIL import Image

        self.width = width
        self.height = height
        self._index = 0
        self._image_type = Image

    def capture(self) -> bytes:
        image = self._image_type.new(
            "RGB", (self.width, self.height),
            (30 + self._index % 40, 90 + (self._index * 7) % 70, 25 + self._index % 30),
        )
        self._index += 1
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    def close(self) -> None:
        pass


class CameraCapture:
    """USB 摄像头采集器，显式释放 OpenCV 资源。"""

    def __init__(self, index: int, width: int, height: int):
        import cv2  # 延迟导入，--fake 不需要 OpenCV

        self._cv2 = cv2
        self._width = width
        self._height = height
        self._cap = cv2.VideoCapture(index)
        if not self._cap.isOpened():
            self._cap.release()
            raise RuntimeError(f"打不开摄像头 index={index}，确认已连接且未被占用")

    def capture(self) -> bytes:
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("读帧失败，检查摄像头是否被占用")
        frame = self._cv2.resize(frame, (self._width, self._height))
        ok, encoded = self._cv2.imencode(
            ".jpg", frame, [self._cv2.IMWRITE_JPEG_QUALITY, 85],
        )
        if not ok:
            raise RuntimeError("JPEG 编码失败")
        return encoded.tobytes()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def gen_boundary(base_lng: float, base_lat: float, total_len_m: float) -> dict[str, Any]:
    """生成包住直线轨迹的演示矩形 GeoJSON Polygon。"""
    half_lng = 15.0 / 111_000.0
    half_lat = (total_len_m + 20.0) / 2 / 111_000.0
    ring = [
        [base_lng - half_lng, base_lat - half_lat],
        [base_lng + half_lng, base_lat - half_lat],
        [base_lng + half_lng, base_lat + half_lat],
        [base_lng - half_lng, base_lat + half_lat],
        [base_lng - half_lng, base_lat - half_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AgriScout 真车采集端")
    parser.add_argument("--api", default="http://localhost:8000", help="后端地址")
    parser.add_argument("--device", default="rover-001", help="设备编号 code")
    parser.add_argument("--field-id", type=int, default=0, help="已有地块 id（0=自动建测试田）")
    parser.add_argument("--field-name", default="真车测试田", help="自动建地块时的名字")
    parser.add_argument("--points", type=int, default=10, help="采样点数量")
    parser.add_argument("--interval", type=float, default=2.0, help="两次拍照间隔秒数（0=不等待）")
    parser.add_argument("--step", type=float, default=0.5, help="相邻采样点间距（米）")
    parser.add_argument("--base-lng", type=float, default=116.100, help="起始经度")
    parser.add_argument("--base-lat", type=float, default=39.100, help="起始纬度")
    parser.add_argument("--camera", type=int, default=0, help="USB 摄像头索引")
    parser.add_argument("--width", type=int, default=640, help="上传照片宽")
    parser.add_argument("--height", type=int, default=480, help="上传照片高")
    parser.add_argument("--sowing-days-ago", type=int, default=50, help="播种于几天前")
    parser.add_argument("--fake", action="store_true", help="不用摄像头，用合成图测试链路")
    parser.add_argument(
        "--spool-dir", default=".rover-spool",
        help="本地巡检包队列目录（断网时保留完整包）",
    )
    parser.add_argument(
        "--upload-retries", type=int, default=2,
        help="临时网络/服务端错误的额外重试次数",
    )
    parser.add_argument(
        "--retry-delay", type=float, default=0.5,
        help="重试基础等待秒数（指数退避）",
    )
    parser.add_argument(
        "--flush-spool", action="store_true",
        help="只补传本地队列，不启动新的采集",
    )
    args = parser.parse_args(argv)
    if args.points < 1:
        parser.error("--points 必须大于 0")
    if args.interval < 0:
        parser.error("--interval 不能为负数")
    if args.step <= 0:
        parser.error("--step 必须大于 0")
    if args.width < 1 or args.height < 1:
        parser.error("--width 和 --height 必须大于 0")
    if args.field_id < 0:
        parser.error("--field-id 不能为负数")
    if args.sowing_days_ago < 0:
        parser.error("--sowing-days-ago 不能为负数")
    if args.upload_retries < 0:
        parser.error("--upload-retries 不能为负数")
    if args.retry_delay < 0:
        parser.error("--retry-delay 不能为负数")
    if not (-180 <= args.base_lng <= 180 and -90 <= args.base_lat <= 90):
        parser.error("--base-lng/--base-lat 超出经纬度范围")
    return args


def ensure_records(client: ApiClient, args: argparse.Namespace) -> tuple[dict, dict, dict]:
    """幂等创建或复用设备、地块、作物和种植记录。"""
    device = client.ensure_device(args.device, f"真车({args.device})")
    field = (
        client.ensure_field(
            args.field_name,
            gen_boundary(args.base_lng, args.base_lat, args.points * args.step),
        )
        if args.field_id == 0 else {"id": args.field_id}
    )
    crop = client.ensure_crop("冬小麦", "济麦22", 240, WHEAT_STAGES)
    sowing = (datetime.now(TZ_CN) - timedelta(days=args.sowing_days_ago)).date().isoformat()
    planting = client.ensure_planting(field["id"], crop["id"], sowing)
    return device, field, planting


def collect_points(
    args: argparse.Namespace,
    source: CaptureSource,
    clock: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[list[dict], list[list[float]], datetime]:
    """采集全部点位；任一点失败都会中止，避免上传不完整巡检包。"""
    capture_points: list[dict] = []
    track: list[list[float]] = []
    timestamps: list[datetime] = []
    clock = clock or (lambda: datetime.now(TZ_CN))
    print(
        f"[采集] 共 {args.points} 点，间隔 {args.interval}s，步长 {args.step}m"
        f"（{'合成图' if args.fake else 'USB 摄像头'}）",
    )
    for index in range(args.points):
        if index and args.interval:
            sleeper(args.interval)
        captured = clock()
        photo_b64 = base64.b64encode(source.capture()).decode("ascii")
        lng = args.base_lng
        lat = round(args.base_lat + (args.step * index) / 111_000.0, 6)
        timestamps.append(captured)
        track.append([lng, lat])
        capture_points.append({
            "seq": index,
            "distance_m": round(args.step * index, 2),
            "lng": lng,
            "lat": lat,
            "captured_at": captured.isoformat(),
            "photo": photo_b64,
            "weather": None,
        })
        print(
            f"  点 {index + 1}/{args.points}：距离 {round(args.step * index, 2)}m，"
            f"坐标({lng},{lat})，照片 {len(photo_b64) // 1024}KB",
        )
    return capture_points, track, timestamps[0]


def build_package(
    field_id: int,
    planting_id: int,
    device_code: str,
    capture_points: list[dict],
    track: list[list[float]],
    start_dt: datetime,
    fake: bool,
) -> dict[str, Any]:
    """将采集结果组装成巡检包 v1，结束时间取最后一个真实采集时间。"""
    end_dt = datetime.fromisoformat(capture_points[-1]["captured_at"])
    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(seconds=1)
    return {
        "patrol": {
            "field_id": field_id,
            "planting_id": planting_id,
            "device": device_code,
            "started_at": start_dt.isoformat(),
            "ended_at": end_dt.isoformat(),
            "track": track,
            "notes": f"rover:{device_code} real/fake={fake}",
        },
        "capture_points": capture_points,
    }


def run(args: argparse.Namespace) -> int:
    client = ApiClient(args.api)
    spool = PackageSpool(args.spool_dir)
    source: CaptureSource | None = None
    try:
        health = client.get("/api/v1/health")
        print(
            f"[联通] 平台 v{health['version']} ({health['environment']}) "
            f"数据库 {health['database']}",
        )
        pending = spool.pending()
        if pending:
            sent, failed = flush_spool(
                client,
                spool,
                retries=args.upload_retries,
                retry_delay=args.retry_delay,
            )
            print(f"[队列] 补传完成：成功 {sent}，保留 {failed}")
        if args.flush_spool:
            return 1 if spool.pending() else 0
        device, field, planting = ensure_records(client, args)
        print(
            f"[建档] 设备={device['code']} 地块=#{field['id']} "
            f"作物=冬小麦 种植#{planting['id']}",
        )
        source = FakeCapture(args.width, args.height) if args.fake else CameraCapture(
            args.camera, args.width, args.height,
        )
        points, track, start_dt = collect_points(args, source)
        package = build_package(
            field["id"], planting["id"], args.device, points, track, start_dt, args.fake,
        )
        queued_path = spool.save(package)
        result = upload_with_retry(
            client,
            package,
            retries=args.upload_retries,
            retry_delay=args.retry_delay,
            package_id=spool.package_id(package),
        )
        spool.remove(queued_path)
        print(
            f"[上传] 巡检包入库 patrol_id={result['patrol_id']} "
            f"照片落盘 {result['photos_saved']} 引用 {result['photos_referenced']}",
        )
        print("[完成] 打开前端巡检任务即可查看轨迹与照片")
        return 0
    except (OSError, RuntimeError, KeyError, ValueError) as exc:
        print(f"[错误] 采集失败：{exc}")
        if "package" in locals() and isinstance(package, dict):
            try:
                queued_path = spool.path_for(package)
                if not queued_path.exists():
                    spool.save(package, last_error=str(exc))
                print(f"[队列] 已保留未确认巡检包：{queued_path}")
            except OSError as spool_exc:
                print(f"[队列] 保存失败，照片可能需要重新采集：{spool_exc}")
        return 1
    finally:
        if source is not None:
            source.close()
        client.close()


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except ValueError as exc:
        print(f"[错误] 参数错误：{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
