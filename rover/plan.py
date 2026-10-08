"""按巡检计划离线执行（计划 0016 阶段 C）。

在有网处用 ``--plan-fetch`` 把平台最近一次巡检计划（D18 的四张名单）连同补拍任务里的视角存成本地计划文件；
进棚后 ``--plan`` 离线执行：只在名单株停车，补拍株按任务的 ``parameters.views`` 拍，其余三类按标准视角序列拍。
每株拍完与否、原因在组包时算好，随巡检包一起排进上传队列；回到有网处上传成功后，用现有的任务状态接口回报。

确认名单是「推给人确认」（D18）：车照常拍新照片供人看，任务由人在待确认页关闭（D20），车不回报这类任务。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from typing import Any

try:
    from . import acquire, positioning
    from .point_store import PointStore
except ImportError:  # 在 rover/ 目录下直接运行 python run.py
    import acquire  # type: ignore[no-redef]
    import positioning  # type: ignore[no-redef]
    from point_store import PointStore  # type: ignore[no-redef]

PLAN_FORMAT = "agriscout-rover-plan/1"
TZ_CN = timezone(timedelta(hours=8))
LISTS = ("confirm", "reshoot", "coverage", "random")
LIST_LABELS = {"confirm": "确认", "reshoot": "补拍", "coverage": "全覆盖", "random": "抽查"}
# 名单 → 任务类型（与平台 planner 一致，D18）
TASK_TYPES = {"confirm": "label", "reshoot": "revisit", "coverage": "coverage", "random": "random"}
OPEN_STATUSES = ("queued", "assigned", "running")
# 车回报的名单；确认任务由人关闭
REPORTED_LISTS = ("reshoot", "coverage", "random")
# 平台任务状态机一次只走一步（与模拟器、前端 confirmApi 同一做法）
COMPLETE_STEPS = {"queued": ("assigned", "running", "completed"), "assigned": ("running", "completed"),
                  "running": ("completed",)}
# 跨垄时经度按每垄 1 米示意错开；坐标沿垄估算，不代表真实定位（计划 0013 已定）
ROW_GAP_M = 1.0


# ---------------------------------------------------------------- 下载与读取


def fetch_plan(client: Any, field_id: int, *, device: str, now: datetime) -> dict[str, Any]:
    """取平台最近一次巡检计划，补上补拍任务的视角，整理成按垄、株排好的停车清单。"""
    latest = client.latest_plan(field_id)
    views_by_task: dict[int, Any] = {}
    for status in OPEN_STATUSES:
        for task in client.list_tasks(field_id=field_id, task_type=TASK_TYPES["reshoot"], status=status, limit=500):
            views_by_task[task["id"]] = (task.get("parameters") or {}).get("views")
    stops: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []
    for list_name in LISTS:
        for item in latest.get(list_name) or []:
            if item["task_status"] not in OPEN_STATUSES:
                # 已完成或作废的任务不再去拍
                skipped.append({"key": item["key"], "list_name": list_name, "task_id": item["task_id"],
                                "task_status": item["task_status"]})
                continue
            views = None
            if list_name == "reshoot":
                raw = views_by_task.get(item["task_id"])
                try:
                    views = acquire.views_to_json(acquire.parse_views(raw)) if raw else None
                except ValueError as exc:
                    warnings.append(f"补拍株 {item['key']} 的任务视角不合法（{exc}）")
                if views is None:
                    warnings.append(f"补拍株 {item['key']} 的任务里没有可用视角，按标准视角序列拍")
            stops.append({
                "key": item["key"], "row_no": item.get("row_no"), "position_no": item.get("position_no"),
                "list_name": list_name, "task_id": item["task_id"], "task_type": item["task_type"], "views": views,
            })
    # 行车顺序：逐垄、垄内按株序号；没有垄号株号的（自定义键）排最后，执行时按布局找不到会跳过
    stops.sort(key=lambda s: (s["row_no"] is None, s["row_no"] or 0, s["position_no"] or 0, s["key"]))
    return {
        "format": PLAN_FORMAT,
        "field_id": field_id,
        "device": device,
        "plan_version": latest["plan_version"],
        "plan_date": str(latest["plan_date"]),
        "generation": latest.get("generation"),
        "generated_at": latest.get("generated_at"),
        "fetched_at": now.isoformat(),
        "window": latest.get("window"),
        "stops": stops,
        "skipped": skipped,
        "warnings": warnings,
    }


def parse_plan(data: Any) -> dict[str, Any]:
    """校验计划文件；出错抛 ValueError（离线时没法回平台重下，越早报错越好）。"""
    if not isinstance(data, dict) or data.get("format") != PLAN_FORMAT:
        raise ValueError(f"不是 rover 计划文件（format 应为 {PLAN_FORMAT}，先用 --plan-fetch 下载）")
    if not isinstance(data.get("field_id"), int) or data["field_id"] < 1:
        raise ValueError("计划文件缺少有效的 field_id")
    try:
        date.fromisoformat(data["plan_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("计划文件的 plan_date 不合法") from exc
    stops = data.get("stops")
    if not isinstance(stops, list):
        raise ValueError("计划文件缺少 stops 列表")
    for index, stop in enumerate(stops):
        where = f"计划第 {index} 株"
        if not isinstance(stop, dict):
            raise ValueError(f"{where}必须是对象")
        if not positioning.valid_key(stop.get("key")):
            raise ValueError(f"{where}的株号不合法：{stop.get('key')!r}")
        if stop.get("list_name") not in LISTS:
            raise ValueError(f"{where}的名单不合法：{stop.get('list_name')!r}")
        if not isinstance(stop.get("task_id"), int) or stop["task_id"] < 1:
            raise ValueError(f"{where}缺少任务 id")
        for field in ("row_no", "position_no"):
            if stop.get(field) is not None and not isinstance(stop[field], int):
                raise ValueError(f"{where}的 {field} 必须是整数")
        if stop.get("views") is not None:
            acquire.parse_views(stop["views"])
    return data


def save_plan(path: str | Path, plan: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=1)
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


def load_plan(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return parse_plan(json.load(handle))


def window_warnings(plan: dict[str, Any], now: datetime) -> list[str]:
    """计划日期不是今天、或不在清晨叶背窗口内时的提示；只提示，不阻止执行（计划 0016-C）。"""
    warnings = []
    today = now.astimezone(TZ_CN).date()
    if plan["plan_date"] != today.isoformat():
        warnings.append(f"计划日期是 {plan['plan_date']}，今天是 {today}；照常执行")
    window = plan.get("window")
    if window:
        day = date.fromisoformat(str(window["date"]))
        start = datetime.combine(day, dtime.fromisoformat(window["start"]), TZ_CN)
        end = datetime.combine(day, dtime.fromisoformat(window["end"]), TZ_CN)
        if not start <= now <= end:
            warnings.append(
                f"计划建议 {day} {window['start']}–{window['end']} 清晨拍叶背（{window.get('reason') or '前一夜湿润'}），"
                "现在不在窗口内；照常执行",
            )
    return warnings


# ---------------------------------------------------------------- 执行


def rows_by_no(rows: Sequence[positioning.RowLayout | dict[str, Any]]) -> dict[int, positioning.RowLayout]:
    """布局（RowLayout 或 meta.json 里存的字典）按垄号索引。"""
    parsed = [row if isinstance(row, positioning.RowLayout) else positioning.RowLayout(**row) for row in rows]
    return {row.row_no: row for row in parsed}


def locate_row(stop: dict[str, Any], rows: dict[int, positioning.RowLayout]) -> positioning.RowLayout | None:
    """计划株在布局里的那一垄；布局里没有这垄、或株序号超出该垄株数时返回 None（这株不停车）。"""
    row = rows.get(stop.get("row_no"))
    position = stop.get("position_no")
    if row is None or not position or not 1 <= position <= row.plants:
        return None
    return row


def stop_views(stop: dict[str, Any], standard: Sequence[acquire.View]) -> list[acquire.View]:
    return acquire.parse_views(stop["views"]) if stop.get("views") else list(standard)


def _at_target(key: str | None, stop: dict[str, Any]) -> bool:
    if not key:
        return False
    return key == stop["key"] or positioning.parse_key(key) == (stop.get("row_no"), stop.get("position_no"))


def _stop_done(points: Sequence[dict], view_count: int) -> bool:
    """这个停车点的每个视角都拍完了（合格或用满次数）。"""
    for view_index in range(view_count):
        mine = [p for p in points if p.get("view_index") == view_index]
        if not mine or not (mine[-1]["view"]["accepted"] or mine[-1].get("reshoot_reason") is not None):
            return False
    return True


def run_plan(
    store: PointStore,
    rig: acquire.Rig,
    stops: Sequence[dict[str, Any]],
    *,
    drive: Any,
    odometer: Any,
    rows: dict[int, positioning.RowLayout],
    standard_views: Sequence[acquire.View],
    policy: acquire.ShootPolicy,
    clock: Callable[[], datetime],
    base_lng: float,
    base_lat: float,
    odometer_source: str = "estimated",
    distance_source: str = "estimated",
    interval: float = 0.0,
    sleeper: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> list[dict]:
    """按停车清单逐株开过去拍；``stop`` 字段记清单序号，续拍时跳过已拍完的株。

    到位后按里程推算株号：推算或标签核对到的就是计划株时，点上的株号用计划里的键（平台上的那株）；
    核对出是别的株，照片照样留下、株号如实记，这条任务在组包时判为没完成。每换一垄偏差从 0 起（假定底盘在垄头对齐里程计），
    续拍时取这一垄断电前最后记下的偏差。
    """
    existing = store.points
    positioner: positioning.Positioner | None = None
    moved = False

    def located(fix: dict[str, Any], stop: dict[str, Any], row: positioning.RowLayout) -> dict[str, Any]:
        if _at_target(fix.get("observation_key"), stop):
            fix = {**fix, "observation_key": stop["key"]}
        return {**fix, "lng": round(base_lng + (row.row_no - 1) * ROW_GAP_M / acquire.METERS_PER_DEG_LAT, 7),
                "lat": round(base_lat + fix["route_chainage_m"] / acquire.METERS_PER_DEG_LAT, 7)}

    for index, stop in enumerate(stops):
        row = locate_row(stop, rows)
        label = f"计划株 {index + 1}/{len(stops)} {stop['key']}（{LIST_LABELS[stop['list_name']]}）"
        if row is None:
            log(f"  {label}：布局里找不到第 {stop.get('row_no')} 垄第 {stop.get('position_no')} 株，不停车")
            continue
        if positioner is None or positioner.row is None or positioner.row.row_no != row.row_no:
            prior = [p for p in existing if p.get("row_no") == row.row_no and "offset_m" in p]
            positioner = positioning.Positioner(row, odometer_source=odometer_source,
                                                offset_m=prior[-1]["offset_m"] if prior else 0.0)
        views = stop_views(stop, standard_views)
        mine = [p for p in existing if p.get("stop") == index]
        if mine and _stop_done(mine, len(views)):
            continue  # 断电前已拍完
        if moved and interval:
            sleeper(interval)
        drive.go_to(row.row_no, row.chainage_of(stop["position_no"]))
        moved = True
        distance = mine[0]["distance_m"] if mine else odometer.distance_m()
        position: dict[str, Any] = {"distance_m": round(distance, 3), "distance_source": distance_source,
                                    "row_no": row.row_no}
        if mine:  # 续拍：沿用断电前这株最后记下的位置（可能已被标签校正）
            position.update({key: mine[-1].get(key) for key in acquire.POSITION_KEYS if key in mine[-1]})
        else:
            position.update(located(positioner.estimate(distance), stop, row))

        def on_tag(tag: str, distance: float = distance, stop: dict[str, Any] = stop,
                   row: positioning.RowLayout = row, positioner: positioning.Positioner = positioner,
                   ) -> dict[str, Any] | None:
            fix = positioner.apply_tag(tag, distance)
            return located(fix, stop, row) if fix else None

        shot = acquire.shoot_stop(store, rig, views, stop=index, position=position, policy=policy, clock=clock,
                                  on_tag=on_tag)
        if shot:
            accepted = sum(1 for p in shot if p["view"]["accepted"])
            key = next((p["observation_key"] for p in reversed(shot) if p["observation_key"]), None)
            log(f"  {label}：{distance:g}m 停车处={key or '未知'} 拍 {len(shot)} 张，合格 {accepted}/{len(views)} 个视角")
    return store.points


# ---------------------------------------------------------------- 结果与回报


def _reasons(points: Sequence[dict]) -> str:
    found: list[str] = []
    for point in points:
        for reason in (point.get("view") or {}).get("quality", {}).get("reasons") or []:
            short = str(reason).split(":", 1)[0]
            if short not in found:
                found.append(short)
    return "、".join(found) or "原因未记"


def judge_stop(
    stop: dict[str, Any], points: Sequence[dict], rows: dict[int, positioning.RowLayout],
) -> tuple[bool, str]:
    """一株拍没拍成：(是否完成, 说明)。补拍要有合格的叶背图，全覆盖和抽查要有一张合格图。"""
    if locate_row(stop, rows) is None:
        return False, f"布局里找不到第 {stop.get('row_no')} 垄第 {stop.get('position_no')} 株，没有停车"
    if not points:
        return False, "没拍到：巡检在这株之前中断"
    where = next((p for p in points if p.get("position_source") == "tag"), points[-1])
    if where.get("observation_key") != stop["key"]:
        return False, f"停车处核对是 {where.get('observation_key') or '未知株'}，不是计划株 {stop['key']}"
    accepted = [p for p in points if p["view"]["accepted"]]
    if stop["list_name"] == "reshoot":
        under = [p for p in points if p["view"]["side"] == "under"]
        good = [p for p in accepted if p["view"]["side"] == "under"]
        if not good:
            return False, f"叶背拍了 {len(under)} 次都不合格（{_reasons(under)}）"
        return True, f"叶背合格 {len(good)} 张，共拍 {len(points)} 张"
    if not accepted:
        return False, f"拍了 {len(points)} 张都不合格（{_reasons(points)}）"
    return True, f"合格 {len(accepted)} 张，共拍 {len(points)} 张"


def task_reports(
    points: Sequence[dict], plan: dict[str, Any], rows: dict[int, positioning.RowLayout],
) -> dict[str, Any]:
    """组包时算好每条任务的结果，随包排队；确认名单不在其中（由人关闭）。"""
    items = []
    for index, stop in enumerate(plan["stops"]):
        done, detail = judge_stop(stop, [p for p in points if p.get("stop") == index], rows)
        items.append({"task_id": stop["task_id"], "task_type": stop.get("task_type"), "list_name": stop["list_name"],
                      "key": stop["key"], "done": done, "detail": detail})
    return {"plan_date": plan["plan_date"], "generation": plan.get("generation"), "items": items}


def summarize(reports: dict[str, Any]) -> str:
    items = reports["items"]
    confirm = [i for i in items if i["list_name"] not in REPORTED_LISTS]
    reported = [i for i in items if i["list_name"] in REPORTED_LISTS]
    done = sum(1 for i in reported if i["done"])
    return (f"计划 {len(items)} 株：补拍/全覆盖/抽查 完成 {done}、未完成 {len(reported) - done}；"
            f"确认株 {sum(1 for i in confirm if i['done'])}/{len(confirm)} 已拍新照片（等人在待确认页确认）")


def report_tasks(
    client: Any,
    reports: dict[str, Any],
    *,
    patrol_id: int,
    call: Callable[[Callable[[], Any]], Any] = lambda fn: fn(),
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """回报任务：先把结果写进 ``result_note``（同时拿到平台上的当前状态），完成的再按状态机走到 completed。

    没完成的只写原因、状态不动，留给下一版计划复用或作废。平台上已结束（409）、已删除（404）或状态刚被别人改了（422）
    的任务跳过；网络错误向上抛，整个包留在队列，下次补传时重来（写说明和走状态都可以重复做）。
    """
    label = f"rover 按 {reports['plan_date']} 巡检计划（第 {reports.get('generation') or '?'} 版）"
    counts = {"completed": 0, "noted": 0, "skipped": 0}
    for item in reports["items"]:
        if item["list_name"] not in REPORTED_LISTS:
            continue
        task_id = item["task_id"]
        note = f"{label}{'已拍' if item['done'] else '未完成'}：{item['detail']}；巡检 #{patrol_id}"
        try:
            current = call(lambda: client.note_task(task_id, note))
            if item["done"]:
                for step in COMPLETE_STEPS.get(current["status"], ()):
                    call(lambda step=step: client.report_task_status(
                        task_id, step, result_note=note if step == "completed" else None))
        except RuntimeError as exc:
            if getattr(exc, "status_code", None) not in (404, 409, 422):
                raise
            counts["skipped"] += 1
            log(f"  任务 #{task_id}（{item['key']}）在平台上已结束或状态刚被改过，不回报：{exc}")
            continue
        counts["completed" if item["done"] else "noted"] += 1
    return counts
