"""多日期模拟季：同一块地按固定间隔反复巡检，病害按潜伏期 + 天气 + 空间扩散发展（执行计划 0008）。

流程（全程只走 HTTP，基线 D5）：
    建档 → 逐日推进病害模型 → 每 N 天一趟全覆盖巡检（照片反映当天可见严重度）
    → 等待分析 → 生成风险预测（带区域历史）→ 模拟农技员随访（真值来自模型）
    → 调平台指标接口 → 导出真值 JSON（供 backend/app/tools/replay_eval.py 离线重放）

模拟季整体放在过去：预测窗口在「现在」之前全部结束，阴性随访才能通过 D10 校验。

用法：
    cd simulator
    ../backend/.venv/bin/python season.py --days 36 --interval 3 --seed 7
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import random
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from client import ApiClient, ApiError
from epidemic import Epidemic, EpidemicConfig, generate_weather
from geo import Layout, area_ha, boundary_geojson, s_path, to_lng_lat
from photo import make_photo_bytes
from run import WHEAT_STAGES

TZ_CN = timezone(timedelta(hours=8))
SECONDS_PER_STEP = 3
MODEL_VERSION = "risk-heuristic-v2"
# 基础巡检照片稳定拍到病斑所需的严重度；低于它只按比例偶尔拍到
BASE_DETECT_SEVERITY = 0.3
TRUTH_SCHEMA = "agriscout.season-truth.v1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AgriScout 多日期病害扩散模拟季")
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--days", type=int, default=36, help="模拟天数")
    p.add_argument("--interval", type=int, default=3, help="巡检间隔（天）")
    p.add_argument("--rows", type=int, default=10)
    p.add_argument("--row-length", type=float, default=30.0)
    p.add_argument("--row-spacing", type=float, default=1.0)
    p.add_argument("--step", type=float, default=0.5)
    p.add_argument("--device", default="sim-season")
    p.add_argument("--field-name", default=None, help="默认 模拟季-<seed>")
    p.add_argument("--origin-lat", type=float, default=39.1100)
    p.add_argument("--origin-lng", type=float, default=116.1100)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--horizon-hours", type=int, default=72, help="预测窗口 H")
    p.add_argument("--target-event", default="条锈病样首次显症（模拟）")
    p.add_argument("--event-severity", type=float, default=0.1,
                   help="随访判定「显症」的区域严重度阈值（近距离复查可见）")
    p.add_argument("--followup-ref", type=float, default=0.25, help="固定参照区域比例（每趟都随访）")
    p.add_argument("--followup-random", type=float, default=0.10, help="每趟额外随机抽查的区域比例")
    p.add_argument("--miss-rate", type=float, default=0.10, help="随访失败（记证据不足）的比例")
    p.add_argument("--truth-out", default=None, help="真值 JSON 输出路径（默认 simulator/out/）")
    p.add_argument("--timeout", type=float, default=180.0, help="每趟等待分析完成的秒数")
    args = p.parse_args(argv)
    if args.days < 2 or args.interval < 1 or args.interval >= args.days:
        p.error("需要 days >= 2 且 1 <= interval < days")
    return args


def season_dates(days: int, horizon_hours: int, today: date | None = None) -> list[date]:
    """模拟季的日期：最后一趟巡检的预测窗口在今天之前结束（留 2 天余量）。"""
    today = today or datetime.now(TZ_CN).date()
    end = today - timedelta(days=math.ceil(horizon_hours / 24) + 2)
    return [end - timedelta(days=days - 1 - d) for d in range(days)]


def build_patrol_package(args, layout: Layout, epi: Epidemic, day: int, when: date, weather) -> dict:
    """某一天的全覆盖巡检包：照片的病斑密度 = 该点所在网格当天的可见严重度。"""
    start = datetime(when.year, when.month, when.day, 9, 0, tzinfo=TZ_CN)
    points, track = [], []
    for seq, (x, y, dist) in enumerate(s_path(layout)):
        rng = random.Random(args.seed * 1_000_003 + day * 10_007 + seq)
        lng, lat = to_lng_lat(x, y, layout)
        severity = epi.severity_at(x, y, day)
        if severity >= BASE_DETECT_SEVERITY:
            mode, intensity = "stress", severity
        elif severity > 0 and rng.random() < severity / BASE_DETECT_SEVERITY:
            # 早期小病斑：巡检视角下只是偶尔拍得到，近距离复查才稳定可见
            mode, intensity = "stress", 0.05
        elif rng.random() < 0.03:  # 背景干扰：土块、枯叶等非病害黄褐色
            mode, intensity = "stress", 0.05
        else:
            mode, intensity = "healthy", 0.0
        photo = None
        if rng.random() < 0.98:
            photo = base64.b64encode(make_photo_bytes(mode, intensity, rng)).decode()
        captured = start + timedelta(seconds=seq * SECONDS_PER_STEP)
        points.append({
            "seq": seq, "distance_m": round(dist, 2), "lng": round(lng, 7), "lat": round(lat, 7),
            "captured_at": captured.isoformat(), "photo": photo,
            "weather": {
                "temp_c": round(weather.temp_c + rng.uniform(-0.5, 0.5), 1),
                "humidity_pct": round(min(100.0, max(0.0, weather.humidity_pct + rng.uniform(-2, 2))), 1),
                "rain_mm": weather.rain_mm,
                "soil_moisture_pct": round(55 + weather.rain_mm + rng.uniform(-2, 2), 1),
            },
        })
        track.append([round(lng, 7), round(lat, 7)])
    return {
        "patrol": {
            "field_id": 0, "device": args.device,
            "started_at": start.isoformat(),
            "ended_at": (start + timedelta(seconds=len(points) * SECONDS_PER_STEP)).isoformat(),
            "track": track[:: max(1, len(track) // 200)],
            "notes": f"season seed={args.seed} day={day}",
        },
        "capture_points": points,
    }


def ingest_or_reuse(client: ApiClient, package: dict) -> int:
    """重跑同一模拟季时同日巡检已存在（409）：复用已有巡检，保证可重复执行。"""
    try:
        return client.ingest_patrol(package)["patrol_id"]
    except ApiError as exc:
        match = re.search(r"HTTP 409.*patrol_id=(\d+)", str(exc))
        if match is None:
            raise
        return int(match[1])


def wait_done(client: ApiClient, patrol_id: int, timeout: float) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get_patrol(patrol_id)["analysis_status"]
        if status in ("done", "error"):
            return status
        time.sleep(0.5)
    return "timeout"


def region_severity(seqs: list[int], xy: dict[int, tuple[float, float]], epi: Epidemic, day: float) -> float:
    return max((epi.severity_at(*xy[s], day) for s in seqs), default=0.0)


def follow_up_region(args, epi, xy, seqs, day: int, dates: list[date], horizon_days: int):
    """按真值给一个区域的首次显症随访：已显症不参与；窗口内首次显症 → 阳性；否则阴性。"""
    if region_severity(seqs, xy, epi, day) >= args.event_severity:
        return None
    for d in range(day + 1, day + horizon_days + 1):
        sev = region_severity(seqs, xy, epi, d)
        if sev >= args.event_severity:
            when = dates[0] + timedelta(days=d)
            event_at = datetime(when.year, when.month, when.day, 8, 0, tzinfo=TZ_CN)
            return "confirmed_positive", event_at, sev
    return "confirmed_negative", None, region_severity(seqs, xy, epi, day + horizon_days)


def run_follow_ups(client, args, epi, xy, patrols, dates) -> dict[str, int]:
    rng = random.Random(args.seed + 99)
    horizon_days = math.ceil(args.horizon_hours / 24)
    all_regions = sorted({p["observation_key"] for patrol in patrols for p in patrol["predictions"]})
    reference = set(rng.sample(all_regions, max(1, round(len(all_regions) * args.followup_ref))))
    counts: dict[str, int] = defaultdict(int)
    for patrol in patrols:
        by_region: dict[str, list[dict]] = defaultdict(list)
        for pred in patrol["predictions"]:
            by_region[pred["observation_key"]].append(pred)
        for key in sorted(by_region):
            if key not in reference and rng.random() >= args.followup_random:
                continue
            preds = by_region[key]
            seqs = [patrol["point_seq"][p["capture_point_id"]] for p in preds]
            outcome = follow_up_region(args, epi, xy, seqs, patrol["day"], dates, horizon_days)
            if outcome is None:
                counts["skipped_already_symptomatic"] += 1
                continue
            status, event_at, severity = outcome
            if rng.random() < args.miss_rate:
                status, event_at = "insufficient", None
            representative = max(preds, key=lambda p: (p["probability"], -p["id"]))
            body = {
                "status": status, "reviewed_by": "模拟农技员",
                "event_confirmed": {"confirmed_positive": True, "confirmed_negative": False}.get(status),
                "event_at": event_at.isoformat() if event_at else None,
                "evidence": {"reference": f"sim://season-{args.seed}/{key}/day{patrol['day']}",
                             "truth_severity": round(severity, 4)},
                "note": {"confirmed_positive": "模拟随访：窗口内首次显症（真值来自模拟器）",
                         "confirmed_negative": "模拟随访：窗口内未显症（真值来自模拟器）",
                         "insufficient": "模拟随访：未能完成复查"}[status],
            }
            client.post_follow_up(representative["id"], body)
            counts[status] += 1
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rng = random.Random(args.seed)
    layout = Layout(rows=args.rows, row_length_m=args.row_length, row_spacing_m=args.row_spacing,
                    step_m=args.step, origin_lat=args.origin_lat, origin_lng=args.origin_lng)
    dates = season_dates(args.days, args.horizon_hours)
    weather = generate_weather(args.days, rng)
    epi = Epidemic((args.rows - 1) * args.row_spacing, args.row_length, EpidemicConfig(days=args.days))
    epi.run(weather, rng)
    xy = {seq: (x, y) for seq, (x, y, _d) in enumerate(s_path(layout))}
    patrol_days = list(range(0, args.days, args.interval))
    print(f"🌾 模拟季：{dates[0]} ~ {dates[-1]}，每 {args.interval} 天巡检一次，共 {len(patrol_days)} 趟；"
          f"每趟 {len(xy)} 点；病害侵染 {epi.summary()['infected_cells']}/{epi.summary()['total_cells']} 格")

    client = ApiClient(args.api, timeout=120.0)
    try:
        client.health()
        device = client.ensure_device(args.device, f"模拟季巡检车({args.device})")
        field = client.ensure_field(args.field_name or f"模拟季-{args.seed}", boundary_geojson(layout),
                                    area_ha=area_ha(layout))
        crop = client.ensure_crop("冬小麦", "济麦22", 240, WHEAT_STAGES)
        sowing = (dates[0] - timedelta(days=50)).isoformat()
        planting = client.ensure_planting(field["id"], crop["id"], sowing)
        print(f"[建档] 设备={device['code']} 地块=#{field['id']}{field['name']} 种植#{planting['id']}（播种 {sowing}）")

        patrols = []
        for day in patrol_days:
            package = build_patrol_package(args, layout, epi, day, dates[day], weather[day])
            package["patrol"]["field_id"] = field["id"]
            package["patrol"]["planting_id"] = planting["id"]
            patrol_id = ingest_or_reuse(client, package)
            status = wait_done(client, patrol_id, args.timeout)
            if status != "done":
                print(f"✗ 巡检 #{patrol_id} 分析未完成：{status}")
                return 1
            preds = client.generate_risk(patrol_id, {
                "target_event": args.target_event, "forecast_hours": args.horizon_hours,
                "model_version": MODEL_VERSION,
            })
            point_seq = {p["id"]: p["seq"] for p in client.list_capture_points(patrol_id)}
            visible = sum(1 for (x, y) in xy.values() if epi.severity_at(x, y, day) >= args.event_severity)
            rising = sum(1 for p in preds if p["trend"] == "rising")
            print(f"  第 {day:>2} 天 {dates[day]} 巡检 #{patrol_id}：适宜度 {weather[day].favourability():.2f}，"
                  f"可见病点 {visible}，预测 {len(preds)} 条（趋势上升 {rising}）")
            patrols.append({"day": day, "date": dates[day].isoformat(), "patrol_id": patrol_id,
                            "predictions": preds, "point_seq": point_seq})

        counts = run_follow_ups(client, args, epi, xy, patrols, dates)
        print(f"[随访] {counts}")
        metrics = client.risk_metrics({
            "target_event": args.target_event, "model_version": MODEL_VERSION,
            "field_id": field["id"], "calibrate": "true",
        })
    except ApiError as exc:
        print(f"✗ API 错误：{exc}")
        return 1
    finally:
        client.close()

    print_metrics(metrics)
    out = Path(args.truth_out) if args.truth_out else Path(__file__).resolve().parent / "out" / f"season-truth-field{field['id']}.json"
    write_truth(out, args, field, dates, weather, patrols, epi, xy, layout)
    print(f"[真值] {out}\n  离线重放：cd backend && .venv/bin/python -m app.tools.replay_eval --truth {out}")
    return 0


def print_metrics(m: dict) -> None:
    cal = m.get("calibration", {})
    fp = m["recall_at_fp"]
    lead = m["lead_time"]
    print("\n═══ 平台指标（来自随访，启发式基线 v2）═══")
    print(f"  可评估 {m['evaluable']}（阳性 {m['positives']}，患病率 {m['prevalence']}）；状态 {m['status_counts']}")
    print(f"  PR-AUC {m['pr_auc']} | Brier {m['brier']} | 校准后 Brier（时间后半段）"
          f"{cal.get('brier_raw')} → {cal.get('brier_calibrated')}")
    print(f"  每地块·日误报 ≤ {fp['fp_per_unit_budget']} 时召回率 {fp['recall']}（阈值 {fp['threshold']}）")
    print(f"  提前量：{lead['events']} 个事件，已预警 {lead['warned']}，漏报率 {lead['missed_rate']}，"
          f"中位提前 {lead['median_lead_hours']} 小时")


def write_truth(out: Path, args, field: dict, dates, weather, patrols, epi: Epidemic, xy, layout: Layout) -> None:
    """真值 JSON：逐点逐日严重度（只存出现过病斑的点）+ 逐日气象 + 巡检映射。"""
    severity: dict[str, list[float]] = {}
    for seq, (x, y) in xy.items():
        series = [epi.severity_at(x, y, d) for d in range(args.days + math.ceil(args.horizon_hours / 24) + 1)]
        if any(series):
            severity[str(seq)] = series
    doc = {
        "schema": TRUTH_SCHEMA,
        "field_id": field["id"], "field_name": field["name"], "seed": args.seed,
        "target_event": args.target_event, "model_version": MODEL_VERSION,
        "horizon_hours": args.horizon_hours, "event_severity": args.event_severity,
        "day0": dates[0].isoformat(),
        "weather": [{"day": w.day, "date": dates[w.day].isoformat(), "temp_c": w.temp_c,
                     "humidity_pct": w.humidity_pct, "rain_mm": w.rain_mm,
                     "leaf_wet_hours": w.leaf_wet_hours, "favourability": w.favourability()}
                    for w in weather],
        "patrols": [{"day": p["day"], "date": p["date"], "patrol_id": p["patrol_id"]} for p in patrols],
        "base_detect_severity": BASE_DETECT_SEVERITY,
        "points": [{"seq": seq, "lng": round(to_lng_lat(x, y, layout)[0], 7),
                    "lat": round(to_lng_lat(x, y, layout)[1], 7)} for seq, (x, y) in xy.items()],
        "severity": severity,
        "epidemic": epi.summary(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
