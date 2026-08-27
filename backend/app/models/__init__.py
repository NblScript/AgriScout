"""模型注册中心：import 即完成全部表映射（Alembic autogenerate 依赖此处完整）。"""
from app.core.db import Base
from app.models.advice import Advice
from app.models.annotation import Annotation
from app.models.analysis import Analysis
from app.models.capture_point import CapturePoint
from app.models.crop import Crop
from app.models.device import Device
from app.models.field import Field
from app.models.patrol import Patrol
from app.models.planting import Planting
from app.models.rule import Rule
from app.models.weather import WeatherSample

__all__ = [
    "Base",
    "Advice",
    "Annotation",
    "Analysis",
    "CapturePoint",
    "Crop",
    "Device",
    "Field",
    "Patrol",
    "Planting",
    "Rule",
    "WeatherSample",
]
