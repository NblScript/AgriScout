"""Field 地块 DTO。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field as PField, field_validator


def _validate_boundary(v: Any) -> dict:
    """轻校验：GeoJSON Polygon 结构（详细几何校验留给 M6 地图端）。"""
    if not isinstance(v, dict):
        raise ValueError("boundary 必须是 GeoJSON 对象")
    if v.get("type") != "Polygon":
        raise ValueError("boundary.type 必须为 'Polygon'")
    coords = v.get("coordinates")
    if not isinstance(coords, list) or not coords or not isinstance(coords[0], list):
        raise ValueError("boundary.coordinates 必须为 [[ [lng,lat], ... ]] 环列表")
    return v


class FieldBase(BaseModel):
    name: str = PField(min_length=1, max_length=100)
    boundary: dict[str, Any]
    area_ha: float | None = PField(default=None, gt=0)
    soil_type: str | None = None
    notes: str | None = None

    @field_validator("boundary")
    @classmethod
    def boundary_must_be_polygon(cls, v: Any) -> dict:
        return _validate_boundary(v)


class FieldCreate(FieldBase):
    pass


class FieldUpdate(BaseModel):
    name: str | None = PField(default=None, min_length=1, max_length=100)
    boundary: dict[str, Any] | None = None
    area_ha: float | None = PField(default=None, gt=0)
    soil_type: str | None = None
    notes: str | None = None

    @field_validator("boundary")
    @classmethod
    def boundary_must_be_polygon(cls, v: Any) -> dict | None:
        return None if v is None else _validate_boundary(v)


class FieldOut(FieldBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
