"""AgriScout 虚拟巡田模拟器 —— 一键闭环：

    建档(设备/地块/作物/种植) → S形垄行 0.5m 采样 → 合成照片+天气曲线
    → 巡检包 HTTP 上传 → 等待后台分析 → 打印建议闭环报告

用法：
    cd simulator
    python run.py --scenario dry            # 干旱场景
    python run.py --scenario patchy_disease # 中段聚集病害斑块
    python run.py --scenario healthy        # 健康对照
依赖：httpx, pillow（见 requirements.txt；可复用 backend/.venv 运行环境）
"""
from __future__ import annotations

import argparse
import base64
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from client import ApiClient, ApiError
from geo import Layout, area_ha, boundary_geojson, s_path, to_lng_lat
from photo import make_photo_bytes
from scenarios import Scenario
from weather import weather_at

TZ_CN = timezone(timedelta(hours=8))
SECONDS_PER_STEP = 3  # 0.5m ÷ ~0.17m/s，与真实小车节拍一致（主计划 §9）

WHEAT_STAGES = [
    {"name": "出苗期", "days": 15},
    {"name": "分蘖期", "days": 30},
    {"name": "拔节期", "days": 25},
    {"name": "抽穗期", "days": 20},
    {"name": "灌浆期", "days": 35},
    {"name": "成熟期", "days": 115},
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AgriScout 虚拟巡田模拟器")
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--scenario", default="healthy",
                   choices=["healthy", "dry", "patchy_disease"])
    p.add_argument("--rows", type=int, default=6)
    p.add_argument("--row-length", type=float, default=24.0)
    p.add_argument("--step", type=float, default=0.5)
    p.add_argument("--row-spacing", type=float, default=1.0)
    p.add_argument("--device", default="sim-001")
    p.add_argument("--field-name", default=None, help="默认 模拟田-<场景>")
    p.add_argument("--origin-lat", type=float, default=39.100)
    p.add_argument("--origin-lng", type=float, default=116.100)
    p.add_argument("--sowing-days-ago", type=int, default=50,
                   help="播种于几天前（50 天前 → 当前处于拔节期）")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timeout", type=float, default=90.0, help="等待分析完成的秒数")
    return p.parse_args()


def build_package(args, scenario: Scenario, rng: random.Random) -> tuple[dict, dict]:
    """生成巡检包。返回 (package, meta) 供建档与报告使用。"""
    layout = Layout(rows=args.rows, row_length_m=args.row_length,
                    row_spacing_m=args.row_spacing, step_m=args.step,
                    origin_lat=args.origin_lat, origin_lng=args.origin_lng)
    profile = scenario.profile

    start_dt = datetime.now(TZ_CN).replace(second=0, microsecond=0)
    capture_points: list[dict] = []
    track: list[list[float]] = []

    local = s_path(layout)
    total = len(local)
    for idx, (x, y, dist) in enumerate(local):
        lng, lat = to_lng_lat(x, y, layout)
        track.append([round(lng, 6), round(lat, 6)])
        captured = start_dt + timedelta(seconds=idx * SECONDS_PER_STEP)
        progress = idx / max(total - 1, 1)
        w = weather_at(captured.hour * 60 + captured.minute, progress, profile, rng)
        mode, intensity = scenario.photo_spec(progress, rng)
        photo_b64 = None
        if rng.random() < 0.97:  # 偶发丢帧，验证缺照片点的容错路径
            photo_b64 = base64.b64encode(
                make_photo_bytes(mode, intensity, rng)
            ).decode()
        capture_points.append({
            "seq": idx,
            "distance_m": round(dist, 2),
            "lng": round(lng, 6),
            "lat": round(lat, 6),
            "captured_at": captured.isoformat(),
            "photo": photo_b64,
            "weather": w,
        })

    package = {
        "patrol": {
            "field_id": 0,  # 由调用方回填
            "device": args.device,
            "started_at": start_dt.isoformat(),
            "ended_at": (start_dt + timedelta(seconds=(total - 1) * SECONDS_PER_STEP)).isoformat(),
            "track": track[:: max(1, len(track) // 200)] or track,  # 轨迹抽稀到 ≤200 点
            "notes": f"simulator:{scenario.name} seed={args.seed}",
        },
        "capture_points": capture_points,
    }
    meta = {
        "layout": layout, "total_points": total,
        "sowing_date": (start_dt - timedelta(days=args.sowing_days_ago)).date().isoformat(),
        "duration_s": (total - 1) * SECONDS_PER_STEP,
    }
    return package, meta


def register_assets(client: ApiClient, args, meta: dict) -> tuple[int, int, int]:
    """幂等建档，返回 (field_id, crop_id, planting_id)。"""
    layout: Layout = meta["layout"]
    device = client.ensure_device(args.device, f"模拟巡检车({args.device})")
    field = client.ensure_field(
        args.field_name or f"模拟田-{args.scenario}",
        boundary_geojson(layout), area_ha=area_ha(layout),
    )
    crop = client.ensure_crop("冬小麦", "济麦22", 240, WHEAT_STAGES)
    planting = client.ensure_planting(field["id"], crop["id"], meta["sowing_date"])
    print(f"[建档] 设备={device['code']} 地块=#{field['id']}{field['name']} "
          f"作物={crop['name']} 种植#{planting['id']} (播种 {meta['sowing_date']})")
    return field["id"], crop["id"], planting["id"]


def wait_analysis(client: ApiClient, patrol_id: int, timeout: float) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        status = client.get_patrol(patrol_id)["analysis_status"]
        if status != last:
            print(f"  分析状态: {status}")
            last = status
        if status in ("done", "error"):
            return status
        time.sleep(0.6)
    return "timeout"


def print_report(client: ApiClient, patrol_id: int, meta: dict) -> None:
    summary = client.get(f"/api/v1/patrols/{patrol_id}/analysis-summary")
    print("\n═══ 分析摘要 ═══")
    print(f"  采样点 {summary['total_points']} | 已分析 {summary['analyzed_points']}"
          f" | 平均NDVI代理 {summary['avg_ndvi']} | 平均风险 {summary['avg_risk_score']}")
    print(f"  长势分布 {summary['vigor_distribution']} | 生育期直方 {summary['stage_histogram']}"
          f" | 胁迫点 {summary['stress_flagged_points']}")

    advices = client.get_advices(patrol_id)
    items = advices["items"]
    tiers: dict[str, int] = {}
    for a in items:
        tier = a["rule_snapshot"]["tier"]
        tiers[tier] = tiers.get(tier, 0) + 1
    print("\n═══ 建议闭环报告 ═══")
    print(f"  共 {len(items)} 条建议，按层分布 {tiers}")

    seen: set[str] = set()
    shown = 0
    for a in items:
        key = a["rule_key"]
        if key in seen:
            continue
        seen.add(key)
        src = a["rule_snapshot"].get("source") or ""
        print(f"  ▸ [{a['priority']:>6}] {key}\n     {a['content'][:64]}\n     出处: {src[:44]}")
        shown += 1
        if shown >= 6:
            break


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    scenario = Scenario.get(args.scenario)
    print(f"🌾 AgriScout 模拟器 · 场景「{scenario.name}」— {scenario.description}")

    client = ApiClient(args.api)
    try:
        health = client.health()
        print(f"[联通] 平台 v{health['version']} ({health['environment']}) 数据库 {health['database']}")
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 平台不可达：{exc}\n  请先启动后端：cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000")
        return 2

    package, meta = build_package(args, scenario, rng)
    field_id, _crop_id, planting_id = register_assets(client, args, meta)
    package["patrol"]["field_id"] = field_id
    package["patrol"]["planting_id"] = planting_id

    print(f"[生成] {meta['total_points']} 个采样点（S形 {args.rows} 垄 × "
          f"{args.row_length}m，步长 {args.step}m），历时约 {meta['duration_s']//60} 分"
          f"（模拟时钟），照片 {sum(1 for cp in package['capture_points'] if cp['photo'])} 张")

    t0 = time.time()
    result = client.ingest_patrol(package)
    print(f"[上传] 巡检包入库 patrol_id={result['patrol_id']} "
          f"({time.time()-t0:.1f}s, 照片落盘 {result['photos_saved']} 引用 {result['photos_referenced']})")

    print("[分析] 等待后台管线…")
    status = wait_analysis(client, result["patrol_id"], args.timeout)
    if status != "done":
        print(f"✗ 分析未完成：{status}")
        return 1

    print_report(client, result["patrol_id"], meta)
    print(f"\n✅ 闭环完成：浏览器打开 http://localhost:5173 可查看该地块与巡检数据")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ApiError as exc:
        print(f"✗ API 错误：{exc}")
        sys.exit(1)
