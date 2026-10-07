"""大棚黄瓜闭环模拟（计划 0017）：真值世界 → 只走 HTTP 的平台闭环 → 导出真值 JSON。

    建大棚地块（facility_type）→ 批量建株档案 → 上报季前到季末的逐小时温湿度
    → 每天：拉巡检计划 → 按名单拍照发 v2 包 → 等分析 → 关拍照任务 → 按真值给确认名单写标注并关确认任务
    → 导出 simulator/out/greenhouse-truth-<seed>.json（后端 app.tools.greenhouse_replay 读它比较巡检策略）

用法（simulator 目录）：
    ../backend/.venv/bin/python greenhouse_run.py --days 10              # 闭环，需操作员账号（AGRISCOUT_USERNAME/PASSWORD）
    ../backend/.venv/bin/python greenhouse_run.py --seed 7 --offline     # 只导出真值，不连平台（离线比较用）

模拟季放在过去：第 0 天 = 今天 − days，最后一天是昨天，计划日的环境截止时刻（当地 08:00）都早于现在。
闭环把计划里的株全部拍完，不设照片上限；上限只在离线比较里用。所有模拟参数都是设计假设（见 greenhouse.py）。
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import random
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from client import ApiClient, ApiError, add_auth_args
from greenhouse import (
    DISCLAIMER, FACILITIES, HUMAN_ERROR, TZ_CN, Layout, PhotoSample, World, human_label, photo_score_band, shoot_view,
    simulate, to_truth,
)
from photo import make_leaf_photo_bytes

OUT_DIR = Path(__file__).resolve().parent / "out"
OFFLINE_DAY0 = date(2026, 3, 2)  # --offline 的默认第 0 天：固定日期让同一种子的真值文件逐字节一致
# 当地拍照时刻：清晨窗口 05:30–08:30 里取 06:30，平时 10:00；每张间隔 15 秒
SHOOT_TIME = {"morning": (6, 30), "day": (10, 0)}
SECONDS_PER_SHOT = 15
CONFIRM_HOUR = 14  # 人工下午看图确认
# 合成叶片图的病斑面积 → 占位分析器风险分（叶背实测均值）：0.46→约 0.83，0.34→约 0.56，0.31→约 0.5，0.08→约 0.1
LESION_FRACTION = {"symptomatic": 0.46, "early": 0.34, "false_positive": 0.31, "none": 0.08}
UPPER_VIEW = {"pitch_deg": -30, "yaw_deg": 0, "height_m": 0.6, "fill_light": False}
UNDER_VIEW = {"pitch_deg": 35, "yaw_deg": 0, "height_m": 0.2, "fill_light": True}
METERS_PER_DEG_LAT = 111_320.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AgriScout 大棚黄瓜闭环模拟（计划 0017）")
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--days", type=int, default=10, help="模拟季天数（每天拉一次计划）")
    p.add_argument("--extra-days", type=int, default=10, help="季后再推几天，只为在真值里查到何时转为明显")
    p.add_argument("--facility", default="solar_greenhouse", choices=FACILITIES)
    p.add_argument("--rows", type=int, default=4)
    p.add_argument("--plants", type=int, default=30, help="每垄株数")
    p.add_argument("--human-error", type=float, default=HUMAN_ERROR, help="人工误判率")
    p.add_argument("--device", default="sim-gh-001")
    p.add_argument("--field-name", default=None, help="默认 模拟大棚-s<种子>-<时间>，每次新建地块")
    p.add_argument("--origin-lat", type=float, default=39.100)
    p.add_argument("--origin-lng", type=float, default=116.100)
    p.add_argument("--day0", type=date.fromisoformat, default=None,
                   help="第 0 天的田间日期；闭环默认今天 − days，--offline 默认 2026-03-02")
    p.add_argument("--offline", action="store_true", help="只生成真值并导出，不连平台")
    p.add_argument("--out", type=Path, default=None, help="真值文件路径，默认 out/greenhouse-truth-<seed>.json")
    p.add_argument("--timeout", type=float, default=120.0, help="每天等待分析完成的秒数")
    add_auth_args(p)
    args = p.parse_args(argv)
    if args.days < 1 or args.extra_days < 0:
        p.error("--days 至少 1，--extra-days 不能为负")
    if not 0 <= args.human_error <= 1:
        p.error("--human-error 取 0–1")
    if args.day0 is None:
        args.day0 = OFFLINE_DAY0 if args.offline else datetime.now(TZ_CN).date() - timedelta(days=args.days)
    elif not args.offline and args.day0 + timedelta(days=args.days) > datetime.now(TZ_CN).date():
        p.error("闭环的模拟季必须在今天之前结束：--day0 + --days 不能晚于今天")
    return args


# ---------------------------------------------------------------- 几何


def plant_xy(layout: Layout, row: int, pos: int) -> tuple[float, float]:
    """棚内局部坐标（米）：x 沿垄，y 跨垄。"""
    return (pos - 1) * layout.spacing_m, (row - 1) * layout.row_spacing_m


def to_lng_lat(x: float, y: float, args) -> tuple[float, float]:
    lat = args.origin_lat + y / METERS_PER_DEG_LAT
    lng = args.origin_lng + x / (METERS_PER_DEG_LAT * math.cos(math.radians(args.origin_lat)))
    return round(lng, 7), round(lat, 7)


def boundary(layout: Layout, args) -> tuple[dict, float]:
    x1 = (layout.plants_per_row - 1) * layout.spacing_m + 0.5
    y1 = (layout.rows - 1) * layout.row_spacing_m + 0.6
    corners = [(-0.5, -0.6), (x1, -0.6), (x1, y1), (-0.5, y1), (-0.5, -0.6)]
    ring = [list(to_lng_lat(x, y, args)) for x, y in corners]
    area_ha = round((x1 + 0.5) * (y1 + 0.6) / 10_000, 4)
    return {"type": "Polygon", "coordinates": [ring]}, area_ha


# ---------------------------------------------------------------- 建档与环境


def setup(client: ApiClient, args, world: World) -> int:
    layout = world.layout
    client.ensure_device(args.device, f"模拟大棚巡检车({args.device})")
    name = args.field_name or f"模拟大棚-s{args.seed}-{datetime.now(TZ_CN):%m%d%H%M}"
    geo, area = boundary(layout, args)
    field = client.post("/api/v1/fields", {
        "name": name, "boundary": geo, "area_ha": area, "facility_type": layout.facility_type,
        "notes": f"greenhouse_run seed={args.seed}；{DISCLAIMER}",
    })
    units = client.post(f"/api/v1/fields/{field['id']}/observation-units/bulk", {"rows": [
        {"row_no": r, "plants": layout.plants_per_row, "spacing_m": layout.spacing_m} for r in range(1, layout.rows + 1)
    ]}, expect=(200, 201))
    # 只上报到季末：季后的天数在未来，不该出现在平台上
    start = datetime.combine(args.day0, datetime.min.time(), tzinfo=TZ_CN)
    readings = [
        {"observed_at": (start + timedelta(hours=h.day * 24 + h.hour)).isoformat(),
         "temp_c": h.temp_c, "humidity_pct": h.humidity_pct}
        for h in world.env if h.day < world.days
    ]
    env = client.post_env_readings(field["id"], "th-sim-01", readings, device=args.device)
    print(f"[建档] 地块 #{field['id']} {name}（{layout.facility_type}，{layout.rows} 垄 × {layout.plants_per_row} 株）"
          f"株档案新建 {units['created']}；温湿度 {env['inserted']} 条（季前 {world.pre_days} 天起，到季末）")
    return field["id"]


# ---------------------------------------------------------------- 一天的拍照


def shoot_day(world: World, plan: dict, day: int, rng: random.Random) -> tuple[str, list[dict]]:
    """按计划拍照（不含确认名单）：补拍只拍叶背、不合格就按计划的角度序列重拍；全覆盖和抽查拍正面一张、
    叶背一张（不合格同样重拍，0016-A 的质量反馈补拍）。返回 (时段, 照片记录)。"""
    period = "morning" if plan.get("window") else "day"
    views = (plan.get("params") or {}).get("reshoot_views") or []
    shots: list[dict] = []

    def add(item: dict, list_name: str, side: str, photos: list[PhotoSample], state: str) -> None:
        for photo in photos:
            view = dict(UPPER_VIEW if side == "upper" else UNDER_VIEW)
            if list_name == "reshoot" and photo.attempt <= len(views):
                planned = views[photo.attempt - 1]
                view.update({k: planned[k] for k in ("pitch_deg", "yaw_deg", "height_m", "fill_light") if k in planned})
            shots.append({"key": item["key"], "task_id": item["task_id"], "list": list_name, "side": side,
                          "state": state, "photo": photo, "view": view})

    for list_name in ("reshoot", "coverage", "random"):
        for item in plan[list_name]:
            state = world.state(item["key"], day)
            if list_name != "reshoot":
                add(item, list_name, "upper", shoot_view(rng, state, "upper", period, world.visibility, reshoot=False), state)
            add(item, list_name, "under", shoot_view(rng, state, "under", period, world.visibility, reshoot=True), state)
    return period, shots


def build_package(world: World, args, field_id: int, day: int, period: str, shots: list[dict],
                  rng: random.Random) -> dict:
    hh, mm = SHOOT_TIME[period]
    date_ = args.day0 + timedelta(days=day)
    start = datetime(date_.year, date_.month, date_.day, hh, mm, tzinfo=TZ_CN)
    plants = {key: (r, p) for key, r, p in world.layout.plants()}
    points = []
    for seq, shot in enumerate(shots):
        photo: PhotoSample = shot["photo"]
        row, pos = plants[shot["key"]]
        x, y = plant_xy(world.layout, row, pos)
        lng, lat = to_lng_lat(x, y, args)
        band = photo_score_band(photo, shot["state"])
        image = make_leaf_photo_bytes(LESION_FRACTION[band], rng, side=shot["side"], blurred=not photo.accepted)
        points.append({
            "seq": seq, "distance_m": round(x, 2), "lng": lng, "lat": lat,
            "captured_at": (start + timedelta(seconds=seq * SECONDS_PER_SHOT)).isoformat(),
            "photo": base64.b64encode(image).decode(),
            "observation_key": shot["key"], "route_chainage_m": round(x, 2),
            "distance_source": "configured", "position_source": "tag",
            "view": {"side": shot["side"], **shot["view"], "attempt": photo.attempt, "accepted": photo.accepted,
                     "quality": {"ok": photo.accepted, "method": "sim-greenhouse"}},
        })
    end = start + timedelta(seconds=max(len(shots) - 1, 1) * SECONDS_PER_SHOT)
    return {
        "schema_version": "2.0",
        "patrol": {
            "field_id": field_id, "device": args.device,
            "started_at": start.isoformat(), "ended_at": end.isoformat(),
            "notes": f"greenhouse_run seed={args.seed} day={day} period={period}",
            "client_package_id": f"gh{field_id}-d{day:03d}-{date_:%Y%m%d}",
        },
        "capture_points": points,
    }


def wait_analysis(client: ApiClient, patrol_id: int, timeout: float) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get_patrol(patrol_id)["analysis_status"]
        if status in ("done", "error"):
            return status
        time.sleep(0.5)
    return "timeout"


STEPS = {"queued": ("assigned", "running", "completed"), "assigned": ("running", "completed"), "running": ("completed",)}


def complete_task(client: ApiClient, task_id: int, status: str, note: str) -> None:
    """按现有状态机把任务走到已完成（与前端 confirmApi 同一做法，D20）。"""
    for step in STEPS.get(status, ()):
        client.report_task_status(task_id, step, result_note=note if step == "completed" else None)


# ---------------------------------------------------------------- 主流程


def run_closed_loop(client: ApiClient, args, world: World) -> dict:
    field_id = setup(client, args, world)
    rng = random.Random(f"greenhouse-run:{args.seed}")
    photo_rng = random.Random(f"greenhouse-photo:{args.seed}")
    history: dict[str, list[dict]] = {}  # 株号 → 已上传的照片（带平台点 id），人工确认时看
    days_log = []
    for day in range(world.days):
        date_ = args.day0 + timedelta(days=day)
        plan = client.post(f"/api/v1/fields/{field_id}/patrol-plans",
                           {"plan_date": date_.isoformat(), "created_by": "simulator"}, expect=(200,))
        period, shots = shoot_day(world, plan, day, rng)
        patrol_id = None
        if shots:
            package = build_package(world, args, field_id, day, period, shots, photo_rng)
            result = client.ingest_patrol(package)
            patrol_id = result["patrol_id"]
            status = wait_analysis(client, patrol_id, args.timeout)
            if status != "done":
                raise ApiError(f"第 {day} 天巡检 #{patrol_id} 分析未完成：{status}")
            ids = {p["seq"]: p["id"] for p in client.list_capture_points(patrol_id)}
            for seq, shot in enumerate(shots):
                history.setdefault(shot["key"], []).append({**shot, "point_id": ids[seq], "day": day})
            tasks = {i["task_id"]: i["task_status"] for n in ("reshoot", "coverage", "random") for i in plan[n]}
            for task_id, task_status in tasks.items():
                complete_task(client, task_id, task_status, f"模拟巡检已拍（巡检 #{patrol_id}）")

        confirms = []
        for item in plan["confirm"]:
            label, point_id, truth = confirm_plant(client, rng, history.get(item["key"], []), args.human_error, day)
            if point_id is not None:
                client.post(f"/api/v1/capture-points/{point_id}/annotations", {
                    "label": label, "annotator_name": "模拟农技员", "note": f"greenhouse_run 第 {day} 天确认",
                })
            complete_task(client, item["task_id"], item["task_status"], f"人工确认：{label}（模拟农技员）")
            confirms.append({"key": item["key"], "label": label, "truth_state": world.state(item["key"], day),
                             "photo_state": truth, "point_id": point_id})

        accepted = sum(1 for s in shots if s["photo"].accepted)
        lists = {n: len(plan[n]) for n in ("confirm", "reshoot", "coverage", "random")}
        print(f"[第 {day:>2} 天 {date_}] 时段 {'清晨' if period == 'morning' else '白天'} "
              f"env_index={plan['env'].get('env_index')} 名单 {lists} 照片 {len(shots)}（合格 {accepted}）"
              f" 巡检 #{patrol_id} 确认 {[c['label'] for c in confirms]}")
        days_log.append({"day": day, "date": date_.isoformat(), "patrol_id": patrol_id, "period": period,
                         "env_index": plan["env"].get("env_index"), "lists": lists,
                         "photos": len(shots), "accepted": accepted, "confirms": confirms})

    states = client.get(f"/api/v1/fields/{field_id}/plant-states")
    counts = Counter(f"{s['state']}/{s['source']}" for s in states)
    print(f"[每株状态] 平台汇总 {dict(sorted(counts.items()))}")
    return {"api": "http", "field_id": field_id, "device": args.device, "days": days_log,
            "plant_states": dict(sorted(counts.items()))}


def confirm_plant(client: ApiClient, rng: random.Random, photos: list[dict], error: float,
                  day: int) -> tuple[str, int | None, str | None]:
    """人看这株最近的合格叶背图和合格正面图下结论；标注挂在最近一张合格叶背图上（没有就挂最近一张照片，D20）。"""
    ok = [p for p in photos if p["photo"].accepted]
    seen = [p for side in ("under", "upper") for p in [next((q for q in reversed(ok) if q["side"] == side), None)] if p]
    seen.sort(key=lambda p: (p["day"], p["point_id"]))
    label = human_label(rng, [(p["state"], p["photo"].detected) for p in seen], error)
    anchor = next((p for p in reversed(ok) if p["side"] == "under"), photos[-1] if photos else None)
    return label, anchor["point_id"] if anchor else None, anchor["state"] if anchor else None


def print_truth_summary(world: World, closed_loop: dict | None) -> None:
    s = world.summary()
    print(f"[真值] {s['plants']} 株；季内侵染 {s['infected_in_season']}、进入早期 {s['early_in_season']}；"
          f"季后 {world.extra_days} 天内明显 {s['symptomatic_by_end']}；季内日均湿润 {s['wet_hours_per_day']} 小时")
    if not closed_loop:
        return
    confirms = [c for d in closed_loop["days"] for c in d["confirms"]]
    positive = {c["key"] for c in confirms if c["label"] != "normal" and c["truth_state"] in ("early", "symptomatic")}
    early_hits = {c["key"] for c in confirms if c["label"] != "normal" and c["truth_state"] == "early"}
    invalid = sum(1 for c in confirms if c["label"] == "normal")
    print(f"[闭环] 人工确认 {len(confirms)} 次（其中确认为健康 {invalid} 次），确认出病株 {len(positive)}（早期就确认 {len(early_hits)}），"
          f"照片 {sum(d['photos'] for d in closed_loop['days'])} 张")


def main() -> int:
    args = parse_args()
    layout = Layout(facility_type=args.facility, rows=args.rows, plants_per_row=args.plants)
    world = simulate(layout, seed=args.seed, days=args.days, extra_days=args.extra_days)
    print(f"🥒 大棚黄瓜闭环模拟 · 种子 {args.seed} · {args.facility} · 第 0 天 {args.day0} · {args.days} 天")
    print(f"   {DISCLAIMER}")
    closed_loop = None
    if not args.offline:
        client = ApiClient(args.api, token=args.token, username=args.username, password=args.password)
        try:
            client.health()
        except Exception as exc:  # noqa: BLE001
            print(f"✗ 平台不可达：{exc}\n  请先启动后端，或加 --offline 只导出真值")
            return 2
        try:
            closed_loop = run_closed_loop(client, args, world)
        finally:
            client.close()
    truth = to_truth(world, args.day0, human_error=args.human_error, closed_loop=closed_loop)
    out = args.out or OUT_DIR / f"greenhouse-truth-{args.seed}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    print_truth_summary(world, closed_loop)
    print(f"[导出] 真值 → {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ApiError as exc:
        print(f"✗ API 错误：{exc}")
        sys.exit(1)
