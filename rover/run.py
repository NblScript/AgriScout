"""AgriScout 真车采集端（树莓派 + USB 摄像头）。

采集端只依赖巡检包 HTTP 协议：建档 → 采集 → 组包 → 上传。
没有摄像头时使用 ``--fake`` 验证完整链路；接入编码器、GPS、传感器时，
只需替换对应的采集源，不需要修改平台后端。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    from . import acquire, hardware, positioning, upload
    from .point_store import PointStore
except ImportError:  # 在 rover/ 目录下直接运行 python run.py
    import acquire  # type: ignore[no-redef]
    import hardware  # type: ignore[no-redef]
    import positioning  # type: ignore[no-redef]
    import upload  # type: ignore[no-redef]
    from point_store import PointStore  # type: ignore[no-redef]

# 相机实现迁到 hardware.py；保留旧名字，旧模式和烟测照常引用
FakeCapture = hardware.FakeCamera
CameraCapture = hardware.CameraCapture

TZ_CN = timezone(timedelta(hours=8))
WHEAT_STAGES = [
    {"name": "出苗期", "days": 15},
    {"name": "分蘖期", "days": 30},
    {"name": "拔节期", "days": 25},
    {"name": "抽穗期", "days": 20},
    {"name": "灌浆期", "days": 35},
    {"name": "成熟期", "days": 115},
]
# 黄瓜生育期：占位值，待农技复核（计划 0016-B4；WP6 定稿）。天数只供平台推算生育期，不作农事依据
CUCUMBER_STAGES = [
    {"name": "发芽期", "days": 7},
    {"name": "幼苗期", "days": 30},
    {"name": "初花期", "days": 20},
    {"name": "结果期", "days": 63},
]
CROPS = {
    # --crop → (作物名, 品种, 生长期天数, 生育期)
    "cucumber": ("黄瓜", "待定（占位，待农技复核）", 120, CUCUMBER_STAGES),
    "wheat": ("冬小麦", "济麦22", 240, WHEAT_STAGES),
}


CaptureSource = hardware.Camera


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

    stops 模式的 v2 包（计划 0016-B）不内嵌照片：信封里的 ``photo_dir`` 指向封存的逐点目录，
    照片在那里一直留到平台确认收包。409 的包标 ``needs_manual``，补传时跳过，等人核对。
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

    def save(
        self, package: dict[str, Any], *, last_error: str | None = None, photo_dir: str | None = None,
    ) -> Path:
        target = self.path_for(package)
        envelope = {
            "package": package,
            "package_id": self.package_id(package),
            "attempts": 0,
            "last_error": last_error,
            "queued_at": datetime.now(TZ_CN).isoformat(),
        }
        if photo_dir is not None:
            envelope["photo_dir"] = photo_dir
        self._write(target, envelope)
        return target

    def _write(self, target: Path, envelope: dict[str, Any]) -> None:
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

    def pending(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"))

    @staticmethod
    def read(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            envelope = json.load(handle)
        if "package" not in envelope or not isinstance(envelope["package"], dict):
            raise ValueError("队列文件缺少 package 对象")
        return envelope["package"], envelope

    def record_failure(
        self, path: Path, envelope: dict[str, Any], error: str, *, needs_manual: bool = False,
    ) -> None:
        current = dict(envelope)
        current["attempts"] = int(envelope.get("attempts", 0)) + 1
        current["last_error"] = error
        if needs_manual:
            current["needs_manual"] = True
        self._write(path, current)

    def photo_root(self, envelope: dict[str, Any]) -> Path | None:
        """v2 包的照片目录；v1 包（照片内嵌）返回 None。"""
        name = envelope.get("photo_dir")
        if name is None:
            return None
        if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"队列文件的 photo_dir 不合法：{name!r}")
        return self.directory / name

    def remove(self, path: Path, photo_root: Path | None = None) -> None:
        # 先删队列文件再删照片目录：中间断电只会留下已封存的照片目录，下次启动时清掉
        path.unlink(missing_ok=True)
        if photo_root is not None:
            shutil.rmtree(photo_root, ignore_errors=True)


class ApiClient(AbstractContextManager["ApiClient"]):
    """平台 HTTP 客户端（只走 HTTP，不 import 后端内部代码）。"""

    def __init__(self, base_url: str, timeout: float = 120.0, *, token: str | None = None,
                 username: str | None = None, password: str | None = None):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("--api 必须是 http:// 或 https:// 地址")
        self.base_url = base_url.rstrip("/")
        # 巡检端通常访问局域网内的后端；不继承主机代理，避免 SOCKS
        # 环境变量把本地请求导向未安装 socksio 的代理适配器。
        self._c = httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False)
        # 登录凭据（决策 D15）：令牌直接用；账号口令在首次 401 时登录，令牌过期后自动重登
        self._username, self._password = username, password
        if token:
            self._c.headers["Authorization"] = f"Bearer {token}"

    def login(self) -> None:
        try:
            resp = self._c.post("/api/v1/auth/login", json={"username": self._username, "password": self._password})
        except httpx.RequestError as exc:
            raise ApiError(f"登录请求失败：{exc}", retryable=True) from exc
        if resp.status_code != 200:
            raise ApiError(f"登录失败 HTTP {resp.status_code}: {resp.text[:200]}", status_code=resp.status_code)
        self._c.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._c.close()

    def _req(self, method: str, path: str, json_body: Any = None, expect=(200, 201), *,
             content: bytes | None = None, headers: dict[str, str] | None = None, params: Any = None):
        def send() -> httpx.Response:
            if content is not None:
                return self._c.request(method, path, content=content, headers=headers, params=params)
            return self._c.request(method, path, json=json_body, headers=headers, params=params)

        try:
            resp = send()
            if resp.status_code == 401 and self._username and self._password:
                self.login()
                resp = send()
        except httpx.RequestError as exc:
            raise ApiError(
                f"{method} {path} 网络请求失败：{exc}", retryable=True,
            ) from exc
        if resp.status_code == 401:
            raise ApiError(
                f"{method} {path} -> HTTP 401：平台要求登录，用 --username/--password"
                "（或环境变量 AGRISCOUT_USERNAME/AGRISCOUT_PASSWORD）或 --token 提供凭据",
                status_code=401,
            )
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
        """提交巡检包：新包 201；同包号同内容的重传 200 + ``duplicate=true``（计划 0014）。"""
        return self.post("/api/v1/ingest/patrol", package, expect=(200, 201))

    def media_exists(self, sha256: str) -> dict[str, Any]:
        """按内容 SHA-256 查平台上是否已有这张照片（计划 0016-B）。"""
        return self._req("GET", "/api/v1/media/exists", params={"sha256": sha256}, expect=(200,))

    def upload_media(self, data: bytes, content_type: str) -> dict[str, Any]:
        """上传一张照片的原始字节，返回 ``{url, sha256, created}``。"""
        return self._req("POST", "/api/v1/media", content=data, headers={"Content-Type": content_type},
                         expect=(200, 201))


def call_with_retry(
    fn: Callable[[], Any],
    *,
    retries: int,
    retry_delay: float = 0.5,
    sleeper: Callable[[float], None] = time.sleep,
    label: str = "",
) -> Any:
    """Call ``fn``; retry only transient failures, never a 409."""
    attempts = max(0, retries) + 1
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except RuntimeError as exc:
            # 409：同包号内容不同（或 v1 包撞上同一开始时间），重试无用，交给人核对
            if isinstance(exc, ApiError) and exc.status_code == 409:
                raise
            retryable = getattr(exc, "retryable", True)
            if not retryable or attempt >= attempts:
                raise
            delay = min(30.0, retry_delay * (2 ** (attempt - 1)))
            print(f"[重试] {label or 'request'} attempt={attempt + 1}/{attempts} 等待 {delay:g}s：{exc}")
            sleeper(delay)
    raise AssertionError("unreachable")


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
    return call_with_retry(
        lambda: client.ingest(package), retries=retries, retry_delay=retry_delay, sleeper=sleeper,
        label=f"package={package_id or 'unknown'}",
    )


def send_queued(
    client: ApiClient,
    spool: PackageSpool,
    path: Path,
    *,
    retries: int,
    retry_delay: float = 0.5,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """上传队列里的一个包。v2 包先逐张查重并上传照片，再提交只含 URL 的元数据包（计划 0016-B）。

    成功（含平台判为重复补传的 200 + duplicate）后删除队列文件和照片目录；409 标记待人工处理；
    其余失败记下原因留在队列，下次补传。
    """
    package, envelope = spool.read(path)
    package_id = envelope.get("package_id") or spool.package_id(package)
    photo_root = spool.photo_root(envelope)
    try:
        if photo_root is not None:
            urls, uploaded = upload.upload_photos(
                client, photo_root, package,
                call=lambda fn: call_with_retry(fn, retries=retries, retry_delay=retry_delay, sleeper=sleeper,
                                                label=f"photo package={package_id}"),
            )
            print(f"[照片] package={package_id} 新传 {uploaded} 张，平台已有 {len(urls) - uploaded} 张")
            package = upload.wire_package(package, urls)
        result = upload_with_retry(
            client, package, retries=retries, retry_delay=retry_delay, sleeper=sleeper, package_id=package_id,
        )
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        conflict = isinstance(exc, ApiError) and exc.status_code == 409
        try:
            spool.record_failure(path, envelope, str(exc), needs_manual=conflict)
        except (OSError, ValueError, KeyError):
            pass
        raise
    spool.remove(path, photo_root)
    return result


def flush_spool(
    client: ApiClient,
    spool: PackageSpool,
    *,
    retries: int,
    retry_delay: float = 0.5,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[int, int]:
    """Replay pending packages; return ``(sent, failed)``. 待人工处理的包跳过，算在 failed 里。"""
    sent = failed = 0
    for path in spool.pending():
        try:
            _, envelope = spool.read(path)
            if envelope.get("needs_manual"):
                failed += 1
                print(f"[队列] {path.name} 待人工处理，跳过：{envelope.get('last_error')}")
                continue
            result = send_queued(client, spool, path, retries=retries, retry_delay=retry_delay, sleeper=sleeper)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            failed += 1
            print(f"[队列] 暂未上传 {path.name}：{exc}")
            continue
        sent += 1
        duplicate = "（平台已有同一个包，按重复补传处理）" if result.get("duplicate") else ""
        print(f"[队列] 已补传 {path.name}{duplicate}")
    return sent, failed


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
    parser.add_argument(
        "--crop", choices=tuple(CROPS), default="cucumber",
        help="自动建种植记录用的作物（黄瓜生育期为占位值，待农技复核）",
    )
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
    # 停车拍摄模式（计划 0016 阶段 A）：每个停车点按视角序列拍、逐张判断质量并补拍、逐点落盘
    parser.add_argument(
        "--mode", choices=("legacy", "stops"), default="stops",
        help="stops=停车按视角序列拍并补拍，照片分步上传（协议 v2）；legacy=沿直线等间隔拍一张（v1 包）",
    )
    parser.add_argument(
        "--views", default=str(Path(__file__).with_name("views.example.json")),
        help="视角序列 JSON（stops 模式）",
    )
    parser.add_argument("--stops", type=int, default=None,
                        help="停车点数量（stops 模式；默认给了布局时为该垄株数，否则 5）")
    parser.add_argument("--stop-spacing", type=float, default=None,
                        help="假里程计的停车点间距（米，stops 模式；默认给了布局时为株距，否则 0.4）")
    parser.add_argument("--layout", default=None,
                        help="棚内布局 JSON（与批量建档同结构，示例 layout.example.json）；给了才按里程推算株号")
    parser.add_argument("--row", type=int, default=None, help="本趟巡哪一垄（默认布局里的第一垄）")
    parser.add_argument("--max-attempts", type=int, default=3, help="每个视角最多拍几次（stops 模式）")
    parser.add_argument("--pitch-step", type=float, default=5.0, help="叶背视角每次补拍加的仰角（度）")
    parser.add_argument(
        "--fake-script", default="",
        help="--fake 时假相机依次产出的图像类型，逗号分隔：normal/blurry/overexposed/dark/backlit",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="stops 模式：继续上次中断的巡检（默认把中断的巡检直接组包排队）",
    )
    # 登录凭据（决策 D15）：口令建议走环境变量，避免留在命令行历史里
    parser.add_argument("--username", default=os.environ.get("AGRISCOUT_USERNAME"), help="平台账号（操作员及以上）")
    parser.add_argument("--password", default=os.environ.get("AGRISCOUT_PASSWORD"), help="口令（建议用环境变量）")
    parser.add_argument("--token", default=os.environ.get("AGRISCOUT_TOKEN"), help="已签发的访问令牌（与账号二选一）")
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
    args.row_layout = None
    if args.layout:
        try:
            args.row_layout = positioning.pick_row(positioning.load_layout(args.layout), args.row)
        except (OSError, ValueError) as exc:
            parser.error(f"--layout 读取失败：{exc}")
    elif args.row is not None:
        parser.error("--row 需要配合 --layout")
    if args.stops is None:
        args.stops = args.row_layout.plants if args.row_layout else 5
    if args.stop_spacing is None:
        args.stop_spacing = args.row_layout.spacing_m if args.row_layout else 0.4
    if args.stops < 1:
        parser.error("--stops 必须大于 0")
    if args.stop_spacing <= 0:
        parser.error("--stop-spacing 必须大于 0")
    if args.max_attempts < 1:
        parser.error("--max-attempts 必须大于 0")
    if args.pitch_step < 0:
        parser.error("--pitch-step 不能为负数")
    script = [kind.strip() for kind in args.fake_script.split(",") if kind.strip()]
    unknown = [kind for kind in script if kind not in hardware.FAKE_KINDS]
    if unknown:
        parser.error(f"--fake-script 不认识的类型：{unknown}")
    args.fake_script = script
    if not (-180 <= args.base_lng <= 180 and -90 <= args.base_lat <= 90):
        parser.error("--base-lng/--base-lat 超出经纬度范围")
    return args


def route_length_m(args: argparse.Namespace) -> float:
    if args.mode == "stops":
        return args.stops * args.stop_spacing
    return args.points * args.step


def ensure_records(client: ApiClient, args: argparse.Namespace) -> tuple[dict, dict, dict]:
    """幂等创建或复用设备、地块、作物和种植记录。"""
    device = client.ensure_device(args.device, f"真车({args.device})")
    field = (
        client.ensure_field(
            args.field_name,
            gen_boundary(args.base_lng, args.base_lat, route_length_m(args)),
        )
        if args.field_id == 0 else {"id": args.field_id}
    )
    name, variety, lifecycle_days, stages = CROPS[args.crop]
    crop = client.ensure_crop(name, variety, lifecycle_days, stages)
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


def seal_patrol(spool: PackageSpool, store: PointStore, *, last_error: str | None = None) -> Path:
    """把一趟 stops 巡检组成 v2 元数据包放进上传队列，并封存逐点目录（照片留到平台确认收包）。

    包号 ``client_package_id`` 就是队列包号（设备、地块、开始时间的哈希），重传时不变。
    先写队列再封存：中间断电时目录仍算未完成，下次启动重新组包，覆盖成同一个队列文件。
    """
    package_id = PackageSpool.package_id({"patrol": store.meta})
    path = spool.save(store.build_package(package_id), last_error=last_error, photo_dir=store.directory.name)
    store.seal(package_id)
    return path


def finalize_unfinished(spool: PackageSpool, *, keep: Path | None = None) -> None:
    """把中断的 stops 巡检（逐点目录）直接组包放进上传队列，已拍的点不丢；清掉已上传巡检的残留照片目录。"""
    for directory, package_id in PointStore.sealed(spool.directory):
        if package_id and not (spool.directory / f"{package_id}.json").exists():
            shutil.rmtree(directory, ignore_errors=True)  # 平台已收包，删队列文件后没来得及删目录
    for directory in PointStore.unfinished(spool.directory):
        if keep is not None and directory == keep:
            continue
        store = PointStore(directory)
        try:
            if not store.resume():
                store.remove()  # 一张都没拍就中断，没有可上传的内容
                continue
            seal_patrol(spool, store, last_error="巡检中断，按已拍的点组包")
        except (OSError, ValueError, KeyError) as exc:
            print(f"[落盘] 中断的巡检 {directory.name} 组包失败，保留目录待人工处理：{exc}")
            continue
        print(f"[落盘] 中断的巡检 {directory.name} 已按 {store.next_seq} 个点组包排队")


def make_rig(args: argparse.Namespace) -> tuple[acquire.Rig, Any]:
    """返回 (Rig, 里程计)。真实云台/补光/编码器尚未接入，非 --fake 时会明确报错。"""
    if args.fake:
        row = args.row_layout
        row_no = row.row_no if row else 1
        rig = acquire.Rig(
            camera=hardware.FakeCamera(args.width, args.height, args.fake_script),
            gimbal=hardware.FakeGimbal(),
            light=hardware.FakeLight(),
            tag_reader=hardware.FakeTagReader([positioning.plant_key(row_no, n) for n in range(1, args.stops + 1)]),
        )
        return rig, hardware.FakeOdometer(args.stop_spacing, start_m=row.start_chainage_m if row else 0.0)
    gimbal, light, odometer = hardware.ServoGimbal(), hardware.GpioLight(), hardware.EncoderOdometer()
    camera = hardware.CameraCapture(args.camera, args.width, args.height)
    return acquire.Rig(camera, gimbal, light, hardware.QrTagReader()), odometer


def open_stops_patrol(
    client: ApiClient, spool: PackageSpool, args: argparse.Namespace, resume_dir: Path | None,
) -> PointStore:
    """新建一趟 stops 巡检的逐点目录；--resume 时打开上次中断的目录。"""
    if resume_dir is not None:
        store = PointStore(resume_dir)
        store.resume()
        print(f"[续拍] 继续巡检 {resume_dir.name}：已落盘 {store.next_seq} 个点")
        return store
    device, field, planting = ensure_records(client, args)
    print(f"[建档] 设备={device['code']} 地块=#{field['id']} 作物={CROPS[args.crop][0]} 种植#{planting['id']}")
    views = acquire.load_views(args.views)
    started = datetime.now(TZ_CN)
    meta = {
        "field_id": field["id"],
        "planting_id": planting["id"],
        "device": args.device,
        "started_at": started.isoformat(),
        "notes": f"rover:{args.device} mode=stops real/fake={args.fake}",
        # 续拍时按建档时的参数继续，避免中途换了视角序列
        "views": acquire.views_to_json(views),
        "stops": args.stops,
        "stop_spacing": args.stop_spacing,
        "max_attempts": args.max_attempts,
        "pitch_step_deg": args.pitch_step,
        "base_lng": args.base_lng,
        "base_lat": args.base_lat,
        # 定位（计划 0016-B3）：本趟巡的那一垄；里程来源决定没读到标签时的 position_source
        "row_layout": asdict(args.row_layout) if args.row_layout else None,
        "fake_odometer": bool(args.fake),
    }
    safe_device = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in args.device)
    return PointStore.create(spool.directory, f"{safe_device}-{started:%Y%m%dT%H%M%S%f}", meta)


def collect_stops(store: PointStore, rig: acquire.Rig, odometer: Any, args: argparse.Namespace) -> None:
    """按 meta 里记下的参数拍完全部停车点（逐点落盘，组包另由 ``seal_patrol`` 做）。"""
    meta = store.meta
    views = acquire.parse_views(meta["views"])
    policy = acquire.ShootPolicy(max_attempts=meta["max_attempts"], pitch_step_deg=meta["pitch_step_deg"])
    print(
        f"[采集] 停车拍摄 {meta['stops']} 个点 × {len(views)} 个视角，每视角最多 {policy.max_attempts} 次"
        f"（{'合成图' if args.fake else 'USB 摄像头'}）",
    )
    row = positioning.RowLayout(**meta["row_layout"]) if meta.get("row_layout") else None
    fake = meta.get("fake_odometer", True)
    acquire.run_stops(
        store, rig, views, odometer,
        stops=meta["stops"], base_lng=meta["base_lng"], base_lat=meta["base_lat"],
        policy=policy, clock=lambda: datetime.now(TZ_CN), interval=args.interval,
        positioner=positioning.Positioner(row, odometer_source="estimated" if fake else "encoder"),
        # 假里程计按配置的停车间距步进；真车读编码器
        distance_source="configured" if fake else "encoder",
    )


def run(args: argparse.Namespace) -> int:
    client = ApiClient(args.api, token=args.token, username=args.username, password=args.password)
    spool = PackageSpool(args.spool_dir)
    source: CaptureSource | None = None
    store: PointStore | None = None
    queued_path: Path | None = None
    try:
        health = client.get("/api/v1/health")
        print(
            f"[联通] 平台 v{health['version']} ({health['environment']}) "
            f"数据库 {health['database']}",
        )
        unfinished = PointStore.unfinished(spool.directory)
        resume_dir = unfinished[-1] if args.mode == "stops" and args.resume and unfinished else None
        if args.resume and resume_dir is None and args.mode == "stops":
            print("[续拍] 没有中断的巡检，开始新的一趟")
        finalize_unfinished(spool, keep=resume_dir)
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
        if args.mode == "stops":
            # 先备好硬件再建目录：真实云台等未接入时直接报错，不留下空的巡检目录
            rig, odometer = make_rig(args)
            source = rig.camera
            store = open_stops_patrol(client, spool, args, resume_dir)
            collect_stops(store, rig, odometer, args)
            queued_path = seal_patrol(spool, store)
            store = None  # 已封存进上传队列
        else:
            device, field, planting = ensure_records(client, args)
            print(
                f"[建档] 设备={device['code']} 地块=#{field['id']} "
                f"作物={CROPS[args.crop][0]} 种植#{planting['id']}",
            )
            source = FakeCapture(args.width, args.height) if args.fake else CameraCapture(
                args.camera, args.width, args.height,
            )
            points, track, start_dt = collect_points(args, source)
            package = build_package(
                field["id"], planting["id"], args.device, points, track, start_dt, args.fake,
            )
            queued_path = spool.save(package)
        result = send_queued(
            client, spool, queued_path, retries=args.upload_retries, retry_delay=args.retry_delay,
        )
        if result.get("duplicate"):
            print(f"[上传] 平台已有同一个巡检包 patrol_id={result['patrol_id']}，按重复补传处理")
        else:
            print(
                f"[上传] 巡检包入库 patrol_id={result['patrol_id']} "
                f"照片落盘 {result['photos_saved']} 引用 {result['photos_referenced']}",
            )
        print("[完成] 打开前端巡检任务即可查看轨迹与照片")
        return 0
    except (OSError, RuntimeError, KeyError, ValueError) as exc:
        print(f"[错误] 采集或上传失败：{exc}")
        if store is not None and store.directory.exists():
            print(f"[落盘] 已拍的 {store.next_seq} 个点保留在 {store.directory}；下次运行加 --resume 续拍，否则自动组包排队")
        if isinstance(exc, ApiError) and exc.status_code == 409 and queued_path is not None:
            print(f"[队列] 平台上已有冲突的巡检包（HTTP 409），已标记待人工处理：{queued_path}")
        elif queued_path is not None and queued_path.exists():
            print(f"[队列] 已保留未确认巡检包：{queued_path}")
        elif "package" in locals() and isinstance(package, dict):
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
