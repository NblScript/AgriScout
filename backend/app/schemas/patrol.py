"""巡检包协议（采集端 ↔ 平台的合同，v1）。

设计约定：
- photo 支持 base64（含 data URI 前缀）或 URL 引用，二选一；
- track 是 [[lng,lat],...] 裸坐标数组，服务端转 GeoJSON LineString 存储；
- 单包单事务：任一点非法则整包拒绝。
"""
import base64
import binascii
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field as PField, field_validator, model_validator

MAX_PHOTO_BYTES = 8 * 1024 * 1024  # 解码后上限 8MB

_URL_PREFIXES = ("http://", "https://", "/media/")
_DATA_URI = "data:image/"


def is_photo_url(value: str) -> bool:
    return value.startswith(_URL_PREFIXES)


def decode_base64_photo(value: str) -> bytes:
    """解码 base64 照片（支持 data URI 前缀），失败/超限抛 ValueError。"""
    payload = value.split(",", 1)[1] if value.startswith(_DATA_URI) else value
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"photo 不是合法 base64：{exc}") from exc
    if len(data) == 0:
        raise ValueError("photo 解码后为空")
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError(f"photo 超过大小上限 {MAX_PHOTO_BYTES // (1024 * 1024)}MB")
    return data


class WeatherPayload(BaseModel):
    """天气快照：全部可空，传感器缺测不阻断接入；有值则做量纲范围校验。"""

    temp_c: float | None = None
    humidity_pct: float | None = PField(default=None, ge=0, le=100)
    light_lux: float | None = PField(default=None, ge=0)
    wind_mps: float | None = PField(default=None, ge=0)
    rain_mm: float | None = PField(default=None, ge=0)
    soil_temp_c: float | None = None
    soil_moisture_pct: float | None = PField(default=None, ge=0, le=100)


class CapturePointPayload(BaseModel):
    seq: int = PField(ge=0)
    distance_m: float = PField(default=0.0, ge=0)
    lng: float = PField(ge=-180, le=180)
    lat: float = PField(ge=-90, le=90)
    captured_at: datetime
    # base64 / URL 二选一；None 表示本点无照片
    photo: str | None = None
    weather: WeatherPayload | None = None

    @field_validator("photo")
    @classmethod
    def photo_shape(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if is_photo_url(v) or v.startswith(_DATA_URI):
            return v
        # 其余按 base64 预校验（提前拦截，避免落库后才发现坏数据）
        decode_base64_photo(v)
        return v


class PatrolHeaderPayload(BaseModel):
    field_id: int = PField(gt=0)
    planting_id: int | None = PField(default=None, gt=0)
    device: str = PField(min_length=1, description="设备编号 code，如 sim-001")
    started_at: datetime
    ended_at: datetime | None = None
    track: list[list[float]] | None = None
    notes: str | None = None

    @field_validator("track")
    @classmethod
    def track_pairs(cls, v: list[list[float]] | None) -> list[list[float]] | None:
        if v is None:
            return v
        for i, pair in enumerate(v):
            if len(pair) != 2:
                raise ValueError(f"track[{i}] 必须是 [lng, lat] 二元组")
            lng, lat = pair
            if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                raise ValueError(f"track[{i}] 坐标越界：lng={lng}, lat={lat}")
        return v

    @model_validator(mode="after")
    def time_order(self) -> "PatrolHeaderPayload":
        if self.started_at and self.ended_at and self.ended_at <= self.started_at:
            raise ValueError("ended_at 必须晚于 started_at")
        return self

    def to_linestring(self) -> dict[str, Any] | None:
        if not self.track:
            return None
        return {"type": "LineString", "coordinates": [list(p) for p in self.track]}


class PatrolPackageIn(BaseModel):
    """巡检包入口协议。"""

    patrol: PatrolHeaderPayload
    capture_points: list[CapturePointPayload] = PField(min_length=1)

    @model_validator(mode="after")
    def seq_unique(self) -> "PatrolPackageIn":
        seqs = [cp.seq for cp in self.capture_points]
        if len(seqs) != len(set(seqs)):
            raise ValueError("capture_points 中存在重复 seq")
        return self


class IngestResultOut(BaseModel):
    patrol_id: int
    capture_points: int
    photos_saved: int    # 本次落盘的照片数
    photos_referenced: int  # 直接引用外部 URL 的照片数
