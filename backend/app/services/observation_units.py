"""株档案：株号解析、按株号找档/自动建档、批量建档（计划 0014）。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ObservationUnit

# 推荐格式 R{垄号两位}-P{株序号三位}，垄号和株序号都从 1 开始（计划 0013「共同约定」）
_RECOMMENDED_RE = re.compile(r"^R(\d{2})-P(\d{3})$")
UNIT_KEY_METHOD = "observation-unit"


def parse_unit_key(key: str) -> tuple[int, int] | None:
    """推荐格式的株号 → (垄号, 株序号)；自定义键或编号为 0 时返回 None。"""
    match = _RECOMMENDED_RE.match(key)
    if match is None:
        return None
    row_no, position_no = int(match[1]), int(match[2])
    if row_no < 1 or position_no < 1:
        return None
    return row_no, position_no


def format_unit_key(row_no: int, position_no: int) -> str:
    return f"R{row_no:02d}-P{position_no:03d}"


def unit_region_key(field_id: int, key: str) -> str:
    """风险输入里的株区域键（与网格键 ``field-{id}/grid…`` 并存，前缀区分类型）。"""
    return f"field-{field_id}/unit/{key}"


def new_unit(field_id: int, key: str, *, created_from: str, **values) -> ObservationUnit:
    parsed = parse_unit_key(key)
    return ObservationUnit(
        field_id=field_id, key=key,
        row_no=parsed[0] if parsed else None,
        position_no=parsed[1] if parsed else None,
        created_from=created_from, **values,
    )


class UnitResolver:
    """一次落库事务内按 (地块, 株号) 找株档案，找不到就自动建档（created_from=ingest，供人工核对）。"""

    def __init__(self, db: Session, field_id: int) -> None:
        self.db = db
        self.field_id = field_id
        self._cache: dict[str, ObservationUnit] = {}
        self.created = 0

    def resolve(self, key: str) -> ObservationUnit:
        unit = self._cache.get(key)
        if unit is None:
            unit = self.db.scalar(select(ObservationUnit).where(
                ObservationUnit.field_id == self.field_id, ObservationUnit.key == key,
            ))
            if unit is None:
                unit = new_unit(self.field_id, key, created_from="ingest")
                self.db.add(unit)
                self.db.flush()
                self.created += 1
            self._cache[key] = unit
        return unit


@dataclass(frozen=True)
class BulkRow:
    row_no: int
    plants: int
    spacing_m: float
    start_chainage_m: float = 0.0


def bulk_create_units(db: Session, field_id: int, rows: list[BulkRow]) -> tuple[int, int]:
    """按推荐格式批量建档；已有的株号跳过（幂等）。返回 (created, skipped)，由调用方提交。"""
    existing = set(db.scalars(select(ObservationUnit.key).where(ObservationUnit.field_id == field_id)))
    created = skipped = 0
    for row in rows:
        for position_no in range(1, row.plants + 1):
            key = format_unit_key(row.row_no, position_no)
            if key in existing:
                skipped += 1
                continue
            chainage = round(row.start_chainage_m + (position_no - 1) * row.spacing_m, 3)
            db.add(new_unit(field_id, key, created_from="bulk", chainage_m=chainage))
            existing.add(key)
            created += 1
    return created, skipped
