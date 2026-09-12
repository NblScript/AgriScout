"""AgriScout 真车采集端（树莓派 + USB 摄像头）。

闭环：拍照 → 攒采样点 → 打包巡检包 → POST 到平台 → 前端地图回放。
与模拟器同权：只走 HTTP 巡检包协议，绝不 import 后端内部代码。

用法示例：
    # 真车（USB 摄像头，逐张间隔 3 秒，拍 20 个点）
    python run.py --api http://10.104.160.64:8000 --device rover-001 --points 20 --interval 3

    # 无摄像头，用合成图测试上传链路（在电脑上也能跑）
    python run.py --fake

当前无传感器：distance_m 按固定步长估算、坐标沿正北走直线、weather 留空；
后续接编码器 / GPS / 温湿光后，再替换对应字段即可（协议字段不变）。
"""
from __future__ import annotations

import argparse
import base64
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

TZ_CN = timezone(timedelta(hours=8))

# 小麦生育期（与模拟器一致，用于建档；规则日历推算依赖它）
WHEAT_STAGES = [
    {"name": "出苗期", "days": 15},
    {"name": "分蘖期", "days": 30},
    {"name": "拔节期", "days": 25},
    {"name": "抽穗期", "days": 20},
    {"name": "灌浆期", "days": 35},
    {"name": "成熟期", "days": 115},
]


class ApiClient:
    """平台 HTTP 客户端（只走 HTTP，不 import 后端）。"""

    def __init__(self, base_url: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self._c = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._c.close()

    def _req(self, method: str, path: str, json_body=None, expect=(200, 201)):
        resp = self._c.request(method, path, json=json_body)
        if resp.status_code not in expect:
            raise RuntimeError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}")
        if method == "DELETE" or not resp.content:
            return None
        return resp.json()

    def get(self, path):
        return self._req("GET", path)

    def post(self, path, body, expect=(200, 201)):
        return self._req("POST", path, json_body=body, expect=expect)

    # ---- 建档助手（幂等：存在即复用）----
    def ensure_device(self, code: str, name: str, model: str = "Robot-Eye Rover"):
        for d in self.get("/api/v1/devices"):
            if d["code"] == code:
                return d
        return self.post("/api/v1/devices", {
            "code": code, "name": name, "type": "rover", "model": model,
        })

    def ensure_field(self, name: str, boundary: dict):
        for f in self.get("/api/v1/fields"):
            if f["name"] == name:
                return f
        return self.post("/api/v1/fields", {
            "name": name, "boundary": boundary, "soil_type": "壤土",
        })

    def ensure_crop(self, name: str, variety: str, lifecycle_days: int, stages: list):
        for c in self.get("/api/v1/crops"):
            if c["name"] == name:
                return c
        return self.post("/api/v1/crops", {
            "name": name, "variety": variety,
            "lifecycle_days": lifecycle_days, "stages": stages,
        })

    def ensure_planting(self, field_id: int, crop_id: int, sowing_date: str):
        for p in self.get(f"/api/v1/plantings?field_id={field_id}&status=active"):
            if p["crop_id"] == crop_id and p["sowing_date"] == sowing_date:
                return p
        return self.post("/api/v1/plantings", {
            "field_id": field_id, "crop_id": crop_id, "sowing_date": sowing_date,
        })

    def ingest(self, package: dict) -> dict:
        return self.post("/api/v1/ingest/patrol", package, expect=(200, 201))


# ---------- 拍照：两种实现（OpenCV 真摄像头 / Pillow 合成图） ----------

def make_camera_capture(index: int, width: int, height: int):
    """USB 摄像头抓帧（OpenCV，延迟 import：--fake 模式不需要）。"""
    import cv2  # opencv-python-headless

    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError(f"打不开摄像头 index={index}，确认已连接、已授权")

    def capture() -> bytes:
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("读帧失败，检查摄像头是否被占用")
        frame = cv2.resize(frame, (width, height))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError("JPEG 编码失败")
        return buf.tobytes()

    return capture, cap


def make_fake_capture(width: int, height: int):
    """合成一张绿色占位图（Pillow，测试链路用，颜色随采样点渐变以区分）。"""
    import io
    from PIL import Image

    state = {"i": 0}

    def capture() -> bytes:
        i = state["i"]
        state["i"] += 1
        # 绿苗底色，色调随点号缓慢变化，便于在回放页区分不同采样点
        g = 90 + (i * 7) % 70
        img = Image.new("RGB", (width, height), (30 + i % 40, g, 25 + i % 30))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    return capture


# ---------- 无 GPS / 无编码器时的坐标与边界估算 ----------

def gen_boundary(base_lng: float, base_lat: float, total_len_m: float) -> dict:
    """生成一个沿正北、包住整条轨迹的矩形 GeoJSON Polygon（演示用）。"""
    half_lng = 15.0 / 111_000.0                     # 东西各约 15m
    half_lat = (total_len_m + 20.0) / 2 / 111_000.0  # 南北各留 10m 余量
    ring = [
        [base_lng - half_lng, base_lat - half_lat],
        [base_lng + half_lng, base_lat - half_lat],
        [base_lng + half_lng, base_lat + half_lat],
        [base_lng - half_lng, base_lat + half_lat],
        [base_lng - half_lng, base_lat - half_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AgriScout 真车采集端")
    p.add_argument("--api", default="http://localhost:8000", help="后端地址（真车填电脑局域网 IP）")
    p.add_argument("--device", default="rover-001", help="设备编号 code")
    p.add_argument("--field-id", type=int, default=0, help="已有地块 id（0=自动建一块测试田）")
    p.add_argument("--field-name", default="真车测试田", help="自动建地块时的名字")
    p.add_argument("--points", type=int, default=10, help="采样点数量")
    p.add_argument("--interval", type=float, default=2.0, help="两次拍照间隔秒数（0=不等待）")
    p.add_argument("--step", type=float, default=0.5, help="相邻采样点间距（米），估算 distance_m 用")
    p.add_argument("--base-lng", type=float, default=116.100, help="起始经度（无 GPS 时的演示坐标）")
    p.add_argument("--base-lat", type=float, default=39.100, help="起始纬度")
    p.add_argument("--camera", type=int, default=0, help="USB 摄像头索引（默认 0）")
    p.add_argument("--width", type=int, default=640, help="上传照片宽")
    p.add_argument("--height", type=int, default=480, help="上传照片高")
    p.add_argument("--sowing-days-ago", type=int, default=50, help="播种于几天前（决定当前生育期）")
    p.add_argument("--fake", action="store_true", help="不用摄像头，用合成图测试链路")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    client = ApiClient(args.api)

    # 1) 联通检查
    try:
        health = client.get("/api/v1/health")
        print(f"[联通] 平台 v{health['version']} ({health['environment']}) 数据库 {health['database']}")
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 平台不可达：{exc}\n  请确认后端已启动，且 --api 指向正确地址")
        return 2

    # 2) 建档（幂等）
    try:
        device = client.ensure_device(args.device, f"真车({args.device})")
        field = client.ensure_field(args.field_name, gen_boundary(args.base_lng, args.base_lat, args.points * args.step)) \
            if args.field_id == 0 else {"id": args.field_id}
        crop = client.ensure_crop("冬小麦", "济麦22", 240, WHEAT_STAGES)
        sowing = (datetime.now(TZ_CN) - timedelta(days=args.sowing_days_ago)).date().isoformat()
        planting = client.ensure_planting(field["id"], crop["id"], sowing)
        print(f"[建档] 设备={device['code']} 地块=#{field['id']} {args.field_name if args.field_id == 0 else ''}"
              f" 作物={crop['name']} 种植#{planting['id']} (播种 {sowing})")
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 建档失败：{exc}")
        return 1

    # 3) 拍照 → 攒点
    capture = make_fake_capture(args.width, args.height) if args.fake else make_camera_capture(
        args.camera, args.width, args.height)[0]
    start_dt = datetime.now(TZ_CN).replace(microsecond=0)
    capture_points, track = [], []

    print(f"[采集] 共 {args.points} 点，间隔 {args.interval}s，步长 {args.step}m（{args.fake and '合成图' or 'USB摄像头'}）")
    for i in range(args.points):
        if i > 0 and args.interval > 0:
            time.sleep(args.interval)
        photo_b64 = base64.b64encode(capture()).decode()
        lng, lat = args.base_lng, round(args.base_lat + (args.step * i) / 111_000.0, 6)
        track.append([lng, lat])
        captured = start_dt + timedelta(seconds=int(i * max(args.interval, 1)))
        capture_points.append({
            "seq": i,
            "distance_m": round(args.step * i, 2),
            "lng": lng,
            "lat": lat,
            "captured_at": captured.isoformat(),
            "photo": photo_b64,
            "weather": None,  # 暂无传感器，留空；接 DHT22 后填 {"temp_c":..., "humidity_pct":...}
        })
        print(f"  点 {i + 1}/{args.points}：距离 {round(args.step * i, 2)}m，坐标({lng},{lat})，照片 {len(photo_b64) // 1024}KB")

    # 4) 打包上传
    package = {
        "patrol": {
            "field_id": field["id"],
            "planting_id": planting["id"],
            "device": args.device,
            "started_at": start_dt.isoformat(),
            "ended_at": (start_dt + timedelta(seconds=int((args.points - 1) * max(args.interval, 1)))).isoformat(),
            "track": track,
            "notes": f"rover:{args.device} real/fake={args.fake}",
        },
        "capture_points": capture_points,
    }
    t0 = time.time()
    result = client.ingest(package)
    print(f"[上传] 巡检包入库 patrol_id={result['patrol_id']} "
          f"({time.time() - t0:.1f}s，照片落盘 {result['photos_saved']} 引用 {result['photos_referenced']})")
    print(f"✅ 完成：浏览器打开 http://localhost:5173 ，进入该地块即可看到轨迹与照片")
    client.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"✗ 错误：{exc}")
        sys.exit(1)
