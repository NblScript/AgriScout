"""巡检包协议（采集端 ↔ 平台的合同，v1 + v2 最小子集）。

设计约定：
- photo 支持 base64（含 data URI 前缀）或 URL 引用，二选一；
- track 是 [[lng,lat],...] 裸坐标数组，服务端转 GeoJSON LineString 存储；
- 单包单事务：任一点非法则整包拒绝；
- v2 最小子集（计划 0014）：包级 schema_version、头部 client_package_id（幂等）、点级
  observation_key / route_chainage_m / distance_source / position_source / view。
  出现任一 v2 字段而 schema_version 不是 "2.0" 时整包拒绝；v1 包行为不变。
"""
import base64
import binascii
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field as PField, field_validator, model_validator

from app.core.timeutil import to_utc

MAX_PHOTO_BYTES = 8 * 1024 * 1024  # 解码后上限 8MB

# 株号 / 包号：标签里的字符串，限定可打印的安全字符（计划 0013「共同约定」）
OBSERVATION_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$"
CLIENT_PACKAGE_ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,64}$"

_URL_PREFIXES = ("http://", "https://", "/media/")
_DATA_URI = "data:image/"


def is_photo_url(value: str) -> bool:
    return value.startswith(_URL_PREFIXES)


def decode_base64_photo(value: str) -> bytes:
    """解码 base64 照片（支持 data URI 前缀），失败/超限抛 ValueError。"""
    if value.startswith(_DATA_URI):
        header, sep, payload = value.partition(",")
        if not sep or ";base64" not in header:
            raise ValueError("photo data URI 须为 data:image/<type>;base64,<数据>")
    else:
        payload = value
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


class ViewPayload(BaseModel):
    """视角元数据（v2，计划 0013「共同约定」）：rover 产出，每株状态使用。"""

    side: Literal["upper", "under", "unknown"] = "unknown"  # 正面 / 叶背 / 未知
    pitch_deg: float | None = PField(default=None, ge=-90, le=90)  # 仰为正
    yaw_deg: float | None = PField(default=None, ge=-180, le=180)
    height_m: float | None = PField(default=None, ge=0)  # 相机离地高度
    fill_light: bool | None = None
    attempt: int = PField(default=1, ge=1)  # 第几次拍（补拍从 2 起）
    accepted: bool | None = None  # 车端质量判断是否合格
    # 车端质量判断结果（iq-rule-v1 结构），宽松接收，只校验 ok 为布尔
    quality: dict[str, Any] | None = None

    @field_validator("quality")
    @classmethod
    def quality_ok_is_bool(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and not isinstance(v.get("ok"), bool):
            raise ValueError("view.quality.ok 必须是布尔值")
        return v


V2_POINT_FIELDS = ("observation_key", "route_chainage_m", "distance_source", "position_source", "view")


class CapturePointPayload(BaseModel):
    seq: int = PField(ge=0)
    distance_m: float = PField(default=0.0, ge=0)
    lng: float = PField(ge=-180, le=180)
    lat: float = PField(ge=-90, le=90)
    captured_at: datetime
    # base64 / URL 二选一；None 表示本点无照片
    photo: str | None = PField(
        default=None,
        description="base64（可带 data URI 前缀）或 URL；/media/ 开头的必须是平台上已有的照片"
                    "（先经 POST /api/v1/media 上传，计划 0016-B），外部 http(s) URL 不校验",
    )
    weather: WeatherPayload | None = None
    # ---- v2 最小子集（schema_version="2.0" 才允许）----
    observation_key: str | None = PField(default=None, pattern=OBSERVATION_KEY_PATTERN, description="株号（标签内容）")
    route_chainage_m: float | None = PField(default=None, ge=0, description="行内位置（米）")
    distance_source: Literal["encoder", "odometry", "configured", "estimated"] | None = None
    position_source: Literal["rtk", "gnss", "tag", "encoder", "estimated", "manual"] | None = None
    view: ViewPayload | None = None

    @field_validator("photo")
    @classmethod
    def photo_shape(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if is_photo_url(v):
            return v
        # base64 与 data URI 一律预校验（提前拦截，避免写盘后才发现坏数据）
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
    # v2：采集端稳定包号，同设备同包号重传按内容哈希判定幂等（计划 0014）
    client_package_id: str | None = PField(default=None, pattern=CLIENT_PACKAGE_ID_PATTERN)

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
        # 统一换算 UTC 再比较：一端带时区一端不带时直接比较会 TypeError（500）；无时区按 UTC 解释（D9）
        if self.started_at and self.ended_at and to_utc(self.ended_at) <= to_utc(self.started_at):
            raise ValueError("ended_at 必须晚于 started_at")
        return self

    def to_linestring(self) -> dict[str, Any] | None:
        if not self.track:
            return None
        return {"type": "LineString", "coordinates": [list(p) for p in self.track]}


class PatrolPackageIn(BaseModel):
    """巡检包入口协议。"""

    schema_version: Literal["1.0", "2.0"] = "1.0"
    patrol: PatrolHeaderPayload
    capture_points: list[CapturePointPayload] = PField(min_length=1)

    @model_validator(mode="after")
    def seq_unique(self) -> "PatrolPackageIn":
        seqs = [cp.seq for cp in self.capture_points]
        if len(seqs) != len(set(seqs)):
            raise ValueError("capture_points 中存在重复 seq")
        return self

    @model_validator(mode="after")
    def v2_fields_need_v2(self) -> "PatrolPackageIn":
        if self.schema_version == "2.0":
            return self
        used = {"patrol.client_package_id"} if self.patrol.client_package_id is not None else set()
        used |= {f"capture_points[].{name}" for cp in self.capture_points
                 for name in V2_POINT_FIELDS if getattr(cp, name) is not None}
        if used:
            raise ValueError(
                f"包里出现了 v2 字段（{'、'.join(sorted(used))}），schema_version 须声明为 \"2.0\"",
            )
        return self


class IngestResultOut(BaseModel):
    patrol_id: int
    capture_points: int
    photos_saved: int    # 本次落盘的照片数
    photos_referenced: int  # 直接引用外部 URL 的照片数
    # 同设备同包号、同内容的重传：返回已有 patrol_id，不重复落库也不重复分析（计划 0014）
    duplicate: bool = False
