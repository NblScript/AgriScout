"""株号定位（计划 0016 阶段 B3）：按棚内布局把里程读数换算成株号，读到标签时以标签为准并校正后续株。

布局 JSON 与平台批量建档（计划 0014）同结构：``{"rows": [{row_no, plants, spacing_m, start_chainage_m}]}``，
第 n 株的行内位置 = start_chainage_m + (n − 1) × spacing_m。

一垄之内：行内位置 = 里程读数 + 偏差，株序号 = round((行内位置 − start) / spacing) + 1。
读到本垄的推荐格式标签时，以标签为准：偏差改为「标签株的布局位置 − 当时的里程读数」，后续株都按新偏差推算，
里程计累积的打滑误差就在每个标签处归零。坐标沿垄估算（计划 0013 已定），不代表真实定位。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 与平台株号正则一致（计划 0013「共同约定」）；不合规的标签内容不上传，否则平台整包拒收
KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_RECOMMENDED = re.compile(r"^R(\d{2})-P(\d{3})$")
POSITION_SOURCES = ("tag", "encoder", "estimated")


def valid_key(key: Any) -> bool:
    return isinstance(key, str) and KEY_PATTERN.match(key) is not None


def plant_key(row_no: int, plant_no: int) -> str:
    return f"R{row_no:02d}-P{plant_no:03d}"


def parse_key(key: str) -> tuple[int, int] | None:
    """推荐格式株号 → (垄号, 株序号)；自定义键或编号为 0 返回 None。"""
    match = _RECOMMENDED.match(key)
    if match is None or int(match[1]) < 1 or int(match[2]) < 1:
        return None
    return int(match[1]), int(match[2])


@dataclass(frozen=True)
class RowLayout:
    row_no: int
    plants: int
    spacing_m: float
    start_chainage_m: float = 0.0

    def __post_init__(self) -> None:
        # 取值范围与平台批量建档一致
        if not 1 <= self.row_no <= 99:
            raise ValueError(f"垄号 {self.row_no} 超出 1–99")
        if not 1 <= self.plants <= 999:
            raise ValueError(f"第 {self.row_no} 垄株数 {self.plants} 超出 1–999")
        if not 0 < self.spacing_m <= 10:
            raise ValueError(f"第 {self.row_no} 垄株距 {self.spacing_m} 须在 (0, 10] 米")
        if self.start_chainage_m < 0:
            raise ValueError(f"第 {self.row_no} 垄起点位置不能为负")

    def chainage_of(self, plant_no: int) -> float:
        return round(self.start_chainage_m + (plant_no - 1) * self.spacing_m, 3)

    def plant_at(self, chainage_m: float) -> int | None:
        plant_no = round((chainage_m - self.start_chainage_m) / self.spacing_m) + 1
        return plant_no if 1 <= plant_no <= self.plants else None


def parse_layout(data: Any) -> list[RowLayout]:
    raw = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError("布局须为 {\"rows\": [...]} 且至少一垄")
    rows = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"布局第 {index} 项必须是对象")
        try:
            rows.append(RowLayout(
                row_no=int(item["row_no"]), plants=int(item["plants"]), spacing_m=float(item["spacing_m"]),
                start_chainage_m=float(item.get("start_chainage_m", 0.0)),
            ))
        except KeyError as exc:
            raise ValueError(f"布局第 {index} 项缺少字段 {exc}") from exc
    numbers = [row.row_no for row in rows]
    if len(numbers) != len(set(numbers)):
        raise ValueError("布局里有重复的垄号")
    return rows


def load_layout(path: str | Path) -> list[RowLayout]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return parse_layout(json.load(handle))


def pick_row(rows: list[RowLayout], row_no: int | None) -> RowLayout:
    if row_no is None:
        return rows[0]
    for row in rows:
        if row.row_no == row_no:
            return row
    raise ValueError(f"布局里没有第 {row_no} 垄")


class Positioner:
    """一垄之内逐个停车点定位。

    ``row`` 为 None（没给布局）时只认标签，株号推算不出来；``odometer_source`` 是没读到标签时的
    ``position_source``：真编码器为 encoder，假里程计为 estimated。
    """

    def __init__(self, row: RowLayout | None, *, odometer_source: str = "estimated", offset_m: float = 0.0):
        if odometer_source not in POSITION_SOURCES:
            raise ValueError(f"odometer_source 必须是 {POSITION_SOURCES} 之一")
        self.row = row
        self.odometer_source = odometer_source
        self.offset_m = offset_m

    def estimate(self, odometer_m: float) -> dict[str, Any]:
        """按里程读数推算：行内位置、株号（推不出为 None）、来源。"""
        chainage = round(max(0.0, odometer_m + self.offset_m), 3)
        plant_no = self.row.plant_at(chainage) if self.row is not None else None
        return {
            "route_chainage_m": chainage,
            "observation_key": plant_key(self.row.row_no, plant_no) if plant_no else None,
            "position_source": self.odometer_source,
            "offset_m": self.offset_m,
        }

    def apply_tag(self, tag: str, odometer_m: float) -> dict[str, Any] | None:
        """本停车点读到标签：以标签为准。本垄的推荐格式标签同时校正偏差；不合规的标签内容忽略（返回 None）。"""
        if not valid_key(tag):
            return None
        parsed = parse_key(tag)
        row = self.row
        if row is not None and parsed is not None and parsed[0] == row.row_no and parsed[1] <= row.plants:
            expected = row.chainage_of(parsed[1])
            self.offset_m = round(expected - odometer_m, 3)
            chainage = expected
        else:
            # 自定义键或别垄的标签：株号以标签为准，位置仍按里程推算，偏差不动
            chainage = round(max(0.0, odometer_m + self.offset_m), 3)
        return {"route_chainage_m": chainage, "observation_key": tag, "position_source": "tag",
                "offset_m": self.offset_m}
