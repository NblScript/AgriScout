"""按视角序列停车拍摄并补拍（计划 0016 阶段 A3）。

每个停车点按视角序列（正面 + 若干叶背仰角）逐个拍；每张当场用 iq-rule-v1 判断质量，
不合格就补拍，叶背视角每次重拍把仰角加 ``pitch_step_deg``。**每次尝试都记成一个点**
（view 里写 attempt / accepted / quality），作为质量反馈的证据；用满次数仍不合格时，
最后一次记 ``reshoot_reason="max_attempts"`` 并继续下一个视角。拍照抛异常时记一个
没有照片的点，不中止整趟。

株号与行内位置由 ``positioning.Positioner`` 按里程推算（计划 0016 阶段 B3）；停车点内读到标签时以标签为准，
从读到的那一张起改用标签株号和校正后的位置，并校正后续停车点。组包时同一停车点统一取标签结果。
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from . import positioning, quality
    from .hardware import Camera, Gimbal, Light, Odometer, TagReader
    from .point_store import PointStore
except ImportError:  # 在 rover/ 目录下直接运行 python run.py
    import positioning  # type: ignore[no-redef]
    import quality  # type: ignore[no-redef]
    from hardware import Camera, Gimbal, Light, Odometer, TagReader  # type: ignore[no-redef]
    from point_store import PointStore  # type: ignore[no-redef]

SIDES = ("upper", "under", "unknown")
METERS_PER_DEG_LAT = 111_000.0
# 停车点级的位置字段（同一停车点的所有点相同；读到标签后整体替换）
POSITION_KEYS = ("route_chainage_m", "observation_key", "position_source", "offset_m", "lng", "lat")


@dataclass(frozen=True)
class View:
    """一个预设视角；字段含义同协议 ``view``（计划 0013「共同约定」）。"""

    name: str
    side: str
    pitch_deg: float
    yaw_deg: float = 0.0
    height_m: float = 0.0
    fill_light: bool = False

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"视角 {self.name!r} 的 side 必须是 {SIDES} 之一")
        if not -90 <= self.pitch_deg <= 90:
            raise ValueError(f"视角 {self.name!r} 的 pitch_deg 超出 -90~90")
        if not -180 <= self.yaw_deg <= 180:
            raise ValueError(f"视角 {self.name!r} 的 yaw_deg 超出 -180~180")
        if self.height_m < 0:
            raise ValueError(f"视角 {self.name!r} 的 height_m 不能为负")


def parse_views(data: Any) -> list[View]:
    raw = data.get("views") if isinstance(data, dict) else data
    if not isinstance(raw, list) or not raw:
        raise ValueError("视角序列必须是非空列表（或 {\"views\": [...]}）")
    views = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"视角 #{index} 必须是对象")
        try:
            views.append(View(
                name=str(item.get("name") or f"view{index}"),
                side=item["side"],
                pitch_deg=float(item["pitch_deg"]),
                yaw_deg=float(item.get("yaw_deg", 0.0)),
                height_m=float(item.get("height_m", 0.0)),
                fill_light=bool(item.get("fill_light", False)),
            ))
        except KeyError as exc:
            raise ValueError(f"视角 #{index} 缺少字段 {exc}") from exc
    return views


def load_views(path: str | Path) -> list[View]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return parse_views(json.load(handle))


@dataclass
class Rig:
    camera: Camera
    gimbal: Gimbal
    light: Light
    tag_reader: TagReader | None = None


@dataclass(frozen=True)
class ShootPolicy:
    max_attempts: int = 3        # 每个视角最多拍几次；待试拍校准
    pitch_step_deg: float = 5.0  # 叶背视角每次重拍加的仰角；待试拍校准
    thresholds: quality.QualityThresholds = quality.DEFAULT_THRESHOLDS


def _last_attempt(points: Sequence[dict], stop: int, view_index: int) -> dict | None:
    """已落盘的点里这个视角的最后一次尝试（断点续拍用）。"""
    mine = [p for p in points if p.get("stop") == stop and p.get("view_index") == view_index]
    return mine[-1] if mine else None


def shoot_view(
    store: PointStore,
    rig: Rig,
    view: View,
    *,
    stop: int,
    view_index: int,
    position: dict[str, Any],
    policy: ShootPolicy,
    clock: Callable[[], datetime],
    tag_state: dict[str, Any],
    first_attempt: int = 1,
    pitch_deg: float | None = None,
) -> list[dict]:
    """拍一个视角直到合格或用满次数；每次尝试都追加一个点并返回这些点。"""
    pitch = view.pitch_deg if pitch_deg is None else pitch_deg
    recorded: list[dict] = []
    if view.fill_light:
        rig.light.set(True)
    try:
        for attempt in range(first_attempt, policy.max_attempts + 1):
            rig.gimbal.move(pitch, view.yaw_deg)
            captured_at = clock()
            photo: bytes | None
            try:
                photo = rig.camera.capture()
            except Exception as exc:  # noqa: BLE001 单张失败不中止整趟，原因写进点记录
                photo = None
                result = quality.failure(f"capture_error: {type(exc).__name__}: {str(exc)[:120]}")
            else:
                try:
                    result = quality.assess(photo, policy.thresholds)
                except OSError as exc:  # 照片解不开：照片照样留存，质量记为不合格
                    result = quality.failure(f"undecodable: {str(exc)[:120]}")
            tags: list[str] = []
            if photo is not None and rig.tag_reader is not None and tag_state.get("key") is None:
                try:
                    tags = rig.tag_reader.read(photo)
                except Exception:  # noqa: BLE001 读不出标签不影响拍摄
                    tags = []
                if tags:
                    tag_state["key"] = tags[0]
                    on_tag = tag_state.get("on_tag")
                    fix = on_tag(tags[0]) if on_tag is not None else None
                    if fix:
                        # 停车点共用同一个 position：本张起、包括本停车点后面的视角，都用标签校正后的位置
                        position.update(fix)
            accepted = bool(result["ok"])
            final = accepted or attempt >= policy.max_attempts
            point = {
                **position,
                "stop": stop,
                "view_index": view_index,
                "captured_at": captured_at.isoformat(),
                # 有定位器时取推算或标签校正后的株号；没有定位器（阶段 A 的用法）时直接用标签
                "observation_key": position.get("observation_key") or tag_state.get("key"),
                "tags": tags,
                "view": {
                    "side": view.side,
                    "pitch_deg": pitch,
                    "yaw_deg": view.yaw_deg,
                    "height_m": view.height_m,
                    "fill_light": view.fill_light,
                    "attempt": attempt,
                    "accepted": accepted,
                    "quality": result,
                },
                "reshoot_reason": "max_attempts" if final and not accepted else None,
            }
            recorded.append(store.append(point, photo))
            if final:
                break
            # 叶背视角拍到了但质量不合格：抬高仰角再拍（多露出叶背）；拍照异常时原角度重试
            if photo is not None and view.side == "under":
                pitch = min(90.0, pitch + policy.pitch_step_deg)
    finally:
        if view.fill_light:
            rig.light.set(False)
    return recorded


def shoot_stop(
    store: PointStore,
    rig: Rig,
    views: Sequence[View],
    *,
    stop: int,
    position: dict[str, Any],
    policy: ShootPolicy,
    clock: Callable[[], datetime],
    on_tag: Callable[[str], dict[str, Any] | None] | None = None,
) -> list[dict]:
    """在一个停车点按视角序列拍摄；已完成的视角（断点续拍时）跳过。

    ``on_tag`` 在本停车点第一次读到标签时调用，返回要并入 ``position`` 的校正字段（None 表示不校正）。
    """
    existing = store.points
    tag_state: dict[str, Any] = {"key": next(
        (p["tags"][0] for p in existing if p.get("stop") == stop and p.get("tags")),
        None,
    ), "on_tag": on_tag}
    recorded: list[dict] = []
    for view_index, view in enumerate(views):
        last = _last_attempt(existing, stop, view_index)
        first_attempt, pitch = 1, None
        if last is not None:
            if last["view"]["accepted"] or last["reshoot_reason"] is not None:
                continue  # 这个视角断电前已经拍完
            first_attempt = last["view"]["attempt"] + 1
            pitch = last["view"]["pitch_deg"]
            if last["photo_file"] and view.side == "under":
                pitch = min(90.0, pitch + policy.pitch_step_deg)
        recorded += shoot_view(
            store, rig, view,
            stop=stop, view_index=view_index, position=position, policy=policy, clock=clock,
            tag_state=tag_state, first_attempt=first_attempt, pitch_deg=pitch,
        )
    return recorded


def run_stops(
    store: PointStore,
    rig: Rig,
    views: Sequence[View],
    odometer: Odometer,
    *,
    stops: int,
    base_lng: float,
    base_lat: float,
    policy: ShootPolicy,
    clock: Callable[[], datetime],
    interval: float = 0.0,
    sleeper: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
    positioner: positioning.Positioner | None = None,
    distance_source: str = "estimated",
) -> list[dict]:
    """逐个停车点拍摄。

    ``distance_m`` 是里程读数，``route_chainage_m`` 是按定位器偏差校正后的行内位置；坐标沿垄按行内位置估算
    （计划 0013 已定，不代表真实定位）。没给定位器时只认标签，株号推不出来。
    """
    existing = store.points
    positioner = positioner or positioning.Positioner(None)
    # 续拍：偏差恢复到断电前最后一个点记下的值（标签校正过的偏差不丢）
    positioner.offset_m = next((p["offset_m"] for p in reversed(existing) if "offset_m" in p), positioner.offset_m)

    def located(fix: dict[str, Any]) -> dict[str, Any]:
        return {**fix, "lng": base_lng, "lat": round(base_lat + fix["route_chainage_m"] / METERS_PER_DEG_LAT, 7)}

    for stop in range(stops):
        distance = odometer.distance_m()  # 每个停车点读一次；续拍时也读，保持假里程计的步进一致
        mine = [p for p in existing if p.get("stop") == stop]
        if mine:
            distance = mine[0]["distance_m"]
        if stop and interval:
            sleeper(interval)
        position = {"distance_m": round(distance, 3), "distance_source": distance_source}
        if mine:  # 续拍：沿用断电前这个停车点最后记下的位置（可能已被标签校正）
            position.update({key: mine[-1].get(key) for key in POSITION_KEYS if key in mine[-1]})
        else:
            position.update(located(positioner.estimate(distance)))

        def on_tag(tag: str, distance: float = distance) -> dict[str, Any] | None:
            fix = positioner.apply_tag(tag, distance)
            return located(fix) if fix else None

        shot = shoot_stop(store, rig, views, stop=stop, position=position, policy=policy, clock=clock,
                          on_tag=on_tag)
        if shot:
            accepted = sum(1 for p in shot if p["view"]["accepted"])
            key = next((p["observation_key"] for p in reversed(shot) if p["observation_key"]), None)
            log(
                f"  停车点 {stop + 1}/{stops}：{distance:g}m 株号={key or '未读到'} "
                f"拍 {len(shot)} 张，合格 {accepted}/{len(views)} 个视角",
            )
    return store.points


def views_to_json(views: Sequence[View]) -> list[dict]:
    return [asdict(view) for view in views]
