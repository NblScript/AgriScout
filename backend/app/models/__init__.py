"""模型注册中心：import 即完成全部表映射（Alembic autogenerate 依赖此处完整）。"""
from app.core.db import Base
from app.models.capture_point import CapturePoint
from app.models.crop import Crop
from app.models.device import Device
from app.models.field import Field
from app.models.patrol import Patrol
from app.models.planting import Planting
from app.models.weather import WeatherSample

__all__ = [
    "Base",
    "CapturePoint",
    "Crop",
    "Device",
    "Field",
    "Patrol",
    "Planting",
    "WeatherSample",
]
