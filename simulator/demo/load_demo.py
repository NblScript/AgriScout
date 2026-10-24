"""巡知（AgriScout）演示数据：两个黄瓜大棚、近两周的叶背巡检、棚内温湿度、今日巡检计划、研究闭环与盲评批次。

只走 HTTP（与模拟器、rover 同口径），不碰数据库文件；日期按「今天」往前推，任何一天加载都能看到当天的计划。
照片是程序画的示意图（绿叶 + 褐斑），不是真实病害照片；数据只用来演示界面和流程，不能当效果证据。

用法（后端已启动、已用 create_user 建好账号；说明见同目录 README.md）：
    export AGRISCOUT_USERNAME=admin AGRISCOUT_PASSWORD='<口令>'
    cd simulator/demo && ../../backend/.venv/bin/python load_demo.py --api http://127.0.0.1:8000

依赖：httpx、Pillow（后端虚拟环境里都有）。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

TZ = timezone(timedelta(hours=8))  # 田间时区（与平台 D9 同口径）
HERE = Path(__file__).resolve().parent
DEVICE = "gh-01"

# 两个大棚的布局与 data/ 下的布局文件一致（rover --layout 可直接用）
GREENHOUSES = {
    "solar": {"name": "1号日光温室（黄瓜）", "facility_type": "solar_greenhouse", "layout": "data/layout-1号日光温室.json",
              "origin": (116.3000, 39.9000)},
    "tunnel": {"name": "2号塑料大棚（黄瓜）", "facility_type": "plastic_tunnel", "layout": "data/layout-2号塑料大棚.json",
               "origin": (116.3020, 39.9000)},
}


# ---------------------------------------------------------------- 工具


def photo(brown: float, seed: int, *, upper: bool = False, dark: float = 1.0) -> str:
    """示意照片：绿底叶脉 + 按比例撒褐斑。brown 越大，平台占位分析器给的风险分越高。"""
    rng = random.Random(seed)
    base = (70, 165, 70) if upper else (46, 150, 62)
    img = Image.new("RGB", (320, 240), tuple(int(v * dark) for v in base))
    d = ImageDraw.Draw(img)
    for _ in range(420):
        x, y = rng.randrange(320), rng.randrange(240)
        d.line((x, y, x + rng.randint(-24, 24), y + rng.randint(-24, 24)),
               fill=(30, int((120 + rng.randint(-20, 20)) * dark), 50), width=2)
    target, done = int(brown * 320 * 240), 0
    while done < target:
        x, y, r = rng.randrange(320), rng.randrange(240), rng.randint(6, 16)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(150, 120, 40) if rng.random() < .5 else (120, 85, 50))
        done += int(3.14 * r * r)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def stable_seed(*parts: object) -> int:
    """跨进程稳定的随机种子（内置 hash() 每次运行都会变，重跑时照片就不一样了）。"""
    return int(hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:8], 16)


class Api:
    def __init__(self, base: str, username: str, password: str) -> None:
        self.http = httpx.Client(base_url=base.rstrip("/") + "/api/v1", timeout=120, trust_env=False)
        resp = self.http.post("/auth/login", json={"username": username, "password": password})
        if resp.status_code != 200:
            sys.exit(f"登录失败（HTTP {resp.status_code}）：{resp.text}")
        self.http.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

    def get(self, path: str, **kw):
        resp = self.http.get(path, **kw)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict, *, ok: tuple[int, ...] = (200, 201)):
        resp = self.http.post(path, json=body)
        if resp.status_code not in ok:
            raise RuntimeError(f"POST {path} → HTTP {resp.status_code}：{resp.text[:300]}")
        return resp.json()


def wait_analysis(api: Api, patrol_id: int, timeout: float = 180) -> str:
    deadline = time.time() + timeout
    status = "pending"
    while time.time() < deadline:
        status = api.get(f"/patrols/{patrol_id}")["analysis_status"]
        if status in ("done", "error"):
            break
        time.sleep(0.5)
    return status


def point(seq: int, key: str, at: datetime, origin: tuple[float, float], *, brown: float, side: str = "under",
          attempt: int = 1, ok: bool = True, reasons: list[str] | None = None, pitch: float | None = None) -> dict:
    row, plant = int(key[1:3]), int(key[5:])
    reasons = reasons or []
    dark = 0.55 if "underexposed" in reasons else 1.0
    return {
        "seq": seq, "lng": round(origin[0] + 0.00004 * plant, 6), "lat": round(origin[1] + 0.00004 * row, 6),
        "captured_at": at.isoformat(),
        "photo": photo(brown, stable_seed(at.date(), key, side, attempt), upper=side == "upper", dark=dark),
        "observation_key": key, "route_chainage_m": round(0.4 * (plant - 1), 3),
        "distance_source": "encoder", "position_source": "tag",
        "view": {"side": side, "pitch_deg": pitch if pitch is not None else (50 if side == "under" else 10),
                 "height_m": 0.6 if side == "under" else 1.1, "fill_light": side == "under",
                 "attempt": attempt, "accepted": ok,
                 "quality": {"method": "iq-rule-v1", "ok": ok, "reasons": reasons}},
    }


def send_patrol(api: Api, field_id: int, package_id: str, start: datetime, points: list[dict]) -> int:
    end = datetime.fromisoformat(points[-1]["captured_at"])
    package = {"schema_version": "2.0",
               "patrol": {"field_id": field_id, "device": DEVICE, "started_at": start.isoformat(),
                          "ended_at": max(end, start + timedelta(seconds=1)).isoformat(),
                          "client_package_id": package_id},
               "capture_points": points}
    result = api.post("/ingest/patrol", package)
    status = "已有（重复补传）" if result.get("duplicate") else wait_analysis(api, result["patrol_id"])
    print(f"  巡检 #{result['patrol_id']} {start:%m-%d %H:%M} {len(points)} 张照片，分析 {status}")
    for warning in result.get("warnings", []):
        print(f"    平台时间提示：{warning}")
    return result["patrol_id"]


def ensure_field(api: Api, spec: dict) -> int:
    for field in api.get("/fields"):
        if field["name"] == spec["name"]:
            return field["id"]
    lng, lat = spec["origin"]
    ring = [[lng, lat], [lng + 0.0006, lat], [lng + 0.0006, lat + 0.0002], [lng, lat + 0.0002], [lng, lat]]
    field = api.post("/fields", {"name": spec["name"], "boundary": {"type": "Polygon", "coordinates": [ring]},
                                 "facility_type": spec["facility_type"]})
    return field["id"]


def build_units(api: Api, field_id: int, layout_path: str) -> list[str]:
    layout = json.loads((HERE / layout_path).read_text(encoding="utf-8"))
    rows = [{k: r[k] for k in ("row_no", "plants", "spacing_m", "start_chainage_m")} for r in layout["rows"]]
    result = api.post(f"/fields/{field_id}/observation-units/bulk", {"rows": rows})
    print(f"  株档案：新建 {result['created']} 株，已有 {result['skipped']} 株")
    return [f"R{r['row_no']:02d}-P{p:03d}" for r in rows for p in range(1, r["plants"] + 1)]


# ---------------------------------------------------------------- 剧情


def demo_day(now: datetime) -> date:
    """「今天」的巡检在清晨 6:10–7:20；还没到 7:30 就用昨天当演示日，免得照片时间晚于上传时间被标「时间存疑」。"""
    today = now.date()
    return today if now.time() >= datetime.strptime("07:30", "%H:%M").time() else today - timedelta(days=1)


def at(day: date, hm: str) -> datetime:
    return datetime.combine(day, datetime.strptime(hm, "%H:%M").time(), tzinfo=TZ)


def load_solar(api: Api, day: date) -> tuple[int, int, int]:
    """1 号日光温室：4 垄 × 12 株。12 天前全覆盖都健康；5 天前起 R01-P005 出现褐斑并向邻株扩散；今天两趟。"""
    spec = GREENHOUSES["solar"]
    print(f"\n[{spec['name']}]")
    field_id = ensure_field(api, spec)
    keys = build_units(api, field_id, spec["layout"])
    origin = spec["origin"]

    history = [  # (几天前, 巡哪几垄, 特殊株 {株号: (褐斑比例, 合格, 原因)})
        (12, (1, 2, 3, 4), {}),
        (5, (1, 2, 3), {"R01-P005": (0.12, True, [])}),
        (3, (1, 2), {"R01-P005": (0.30, True, []), "R01-P006": (0.18, True, []), "R01-P004": (0.10, True, []),
                     "R02-P003": (0.05, False, ["blurry"])}),
    ]
    for days_ago, rows, special in history:
        d = day - timedelta(days=days_ago)
        start = at(d, "06:30")
        points = []
        for key in keys:
            if int(key[1:3]) not in rows or key == "R04-P012":  # R04-P012 一直没拍到（展示「缺拍」）
                continue
            brown, ok, reasons = special.get(key, (0.02, True, []))
            points.append(point(len(points), key, start + timedelta(seconds=20 * len(points)), origin,
                                brown=brown, ok=ok, reasons=reasons))
        send_patrol(api, field_id, f"demo-solar-{d.isoformat()}", start, points)

    # 今天 06:20：全棚叶背 + 部分正面，三株补拍（其中一株两次都不合格）
    brown_today = {"R01-P005": 0.34, "R01-P006": 0.2, "R02-P007": 0.16, "R03-P002": 0.12, "R04-P003": 0.08}
    reshoot = {"R02-P003": [(1, False, ["blurry"]), (2, True, [])],
               "R03-P009": [(1, False, ["overexposed", "backlit"]), (2, False, ["underexposed"])],
               "R04-P006": [(1, False, ["blurry"]), (2, True, [])]}
    upper = {"R01-P002", "R01-P005", "R01-P006", "R02-P007", "R03-P002", "R03-P010"}
    start = at(day, "06:20")
    points = []
    for key in keys:
        if key == "R04-P012":
            continue
        brown = brown_today.get(key, 0.02)
        if key in upper:
            points.append(point(len(points), key, start + timedelta(seconds=15 * len(points)), origin,
                                brown=brown, side="upper"))
        for attempt, ok, reasons in reshoot.get(key, [(1, True, [])]):
            points.append(point(len(points), key, start + timedelta(seconds=15 * len(points)), origin,
                                brown=brown, attempt=attempt, ok=ok, reasons=reasons))
    morning = send_patrol(api, field_id, f"demo-solar-{day.isoformat()}", start, points)

    # 今天 07:05：按计划给几株补拍叶背，褐斑加重，模型分过「推给人确认」的阈值
    brown_second = {"R01-P006": 0.3, "R02-P007": 0.27, "R03-P002": 0.32, "R02-P008": 0.25, "R04-P003": 0.29,
                    "R03-P005": 0.42, "R02-P003": 0.04}
    start = at(day, "07:05")
    points = [point(i, key, start + timedelta(seconds=40 * i), origin, brown=brown, pitch=55)
              for i, (key, brown) in enumerate(brown_second.items())]
    send_patrol(api, field_id, f"demo-solar-{day.isoformat()}-b", start, points)
    return field_id, morning, len(keys)


def load_env(api: Api, field_id: int, day: date, now: datetime, out_dir: Path) -> None:
    """温湿度记录仪 th-01：12 天前到现在每 10 分钟一条；5 天前起夜间高湿（结露），霜霉病环境风险升高。"""
    start = datetime.combine(day - timedelta(days=12), datetime.min.time(), tzinfo=TZ)
    wet_from = datetime.combine(day - timedelta(days=5), datetime.strptime("12:00", "%H:%M").time(), tzinfo=TZ)
    end = min(now, datetime.combine(day, datetime.strptime("23:50", "%H:%M").time(), tzinfo=TZ))
    rows, readings, t = ["时间,温度,湿度"], [], start
    while t <= end:
        h = t.hour + t.minute / 60
        night = h >= 19 or h < 7
        if night:
            temp, rh = (15.6, 97.0) if t >= wet_from else (17.0, 84.0)
        else:
            temp, rh = (round(24.5 + 3.5 * (1 - abs(h - 13) / 6), 1), 69.0)
        rows.append(f"{t:%Y/%m/%d %H:%M:%S},{temp:.1f},{rh:.1f}%")
        readings.append({"observed_at": t.isoformat(), "temp_c": temp, "humidity_pct": rh})
        t += timedelta(minutes=10)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "th-01.csv"
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = api.post(f"/fields/{field_id}/env-readings",
                      {"sensor_key": "th-01", "device": DEVICE, "source": "import", "readings": readings})
    print(f"  温湿度 th-01：新写 {result.get('inserted', '?')} 条，已有跳过 {result.get('skipped', 0)} 条"
          f"（同样的数据另存为 {csv_path}，可用 rover/env_upload.py 练习上传）")


def load_tunnel(api: Api, day: date) -> int:
    """2 号塑料大棚：3 垄 × 10 株，没装温湿度记录仪；今天清晨一趟叶背，R02-P004 有褐斑。"""
    spec = GREENHOUSES["tunnel"]
    print(f"\n[{spec['name']}]")
    field_id = ensure_field(api, spec)
    keys = build_units(api, field_id, spec["layout"])
    special = {"R02-P004": (0.22, True, []), "R02-P005": (0.08, True, []),
               "R03-P007": (0.03, False, ["blurry", "underexposed"])}
    start = at(day, "06:10")
    points = []
    for key in keys:
        if key in ("R03-P009", "R03-P010"):  # 第 3 垄末端两株今天没拍到
            continue
        brown, ok, reasons = special.get(key, (0.02, True, []))
        points.append(point(len(points), key, start + timedelta(seconds=20 * len(points)), spec["origin"],
                            brown=brown, ok=ok, reasons=reasons))
    send_patrol(api, field_id, f"demo-tunnel-{day.isoformat()}", start, points)
    return field_id


def make_plan(api: Api, field_id: int, day: date) -> None:
    plan = api.post(f"/fields/{field_id}/patrol-plans", {"plan_date": day.isoformat(), "created_by": "演示"})
    counts = "、".join(f"{label} {len(plan[k])} 株" for k, label in
                      (("confirm", "推给人确认"), ("reshoot", "叶背补拍"), ("coverage", "全覆盖"), ("random", "随机抽查")))
    print(f"  今日计划（{day}）：{counts}")


def main() -> int:
    parser = argparse.ArgumentParser(description="加载巡知演示数据（只走 HTTP）")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--username", default=os.environ.get("AGRISCOUT_USERNAME"), help="平台账号（操作员及以上）")
    parser.add_argument("--password", default=os.environ.get("AGRISCOUT_PASSWORD"), help="口令（建议用环境变量）")
    parser.add_argument("--skip-research", action="store_true", help="不生成研究闭环的风险预测、复巡任务和盲评批次")
    args = parser.parse_args()
    if not args.username or not args.password:
        sys.exit("缺少账号：设置环境变量 AGRISCOUT_USERNAME / AGRISCOUT_PASSWORD，或用 --username / --password")

    api = Api(args.api, args.username, args.password)
    health = api.get("/health")
    print(f"平台 v{health['version']}（{health['environment']}），数据库 {health['database']}")
    now = datetime.now(TZ)
    day = demo_day(now)
    print(f"演示日：{day}（今天的巡检在清晨 6:10–7:20）")
    api.post("/devices", {"code": DEVICE, "name": "温室巡检车", "type": "rover"}, ok=(200, 201, 409))

    solar_id, morning_patrol, plants = load_solar(api, day)
    load_env(api, solar_id, day, now, HERE.parent / "out" / "demo")  # simulator/out/ 不进 git
    tunnel_id = load_tunnel(api, day)

    # 计划按真实的今天生成：清晨前加载时，就是根据昨天的巡检给今天早上排的计划
    print("\n[今日巡检计划]")
    make_plan(api, solar_id, now.date())
    make_plan(api, tunnel_id, now.date())

    if not args.skip_research:
        print("\n[研究闭环]")
        preds = api.post(f"/patrols/{morning_patrol}/risk-predictions/generate",
                         {"target_event": "目标病害首次显症", "forecast_hours": 48})
        print(f"  风险预测 {len(preds)} 条（今天 06:20 那趟）")
        tasks = api.post("/revisit-tasks/generate", {"field_id": solar_id, "patrol_id": morning_patrol, "limit": 8})
        print(f"  复巡 / 标注任务 {len(tasks)} 条")
        batch = api.post("/blind-reviews", {
            "field_id": solar_id, "name": "演示盲评批次", "date_from": (day - timedelta(days=12)).isoformat(),
            "date_to": day.isoformat(), "sample_size": 12, "seed": 7, "reference_keys": ["R01-P005"],
            "side": "under", "double_review": True})
        print(f"  盲评批次 #{batch['id']}：{batch['item_count']} 张照片，等两位判读人在「盲法复核」页判读")

    print(f"\n完成：1号日光温室 {plants} 株、2号塑料大棚 30 株。打开前端「工作台」查看。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
