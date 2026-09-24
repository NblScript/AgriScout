"""模型注册中心：import 即完成全部表映射（Alembic autogenerate 依赖此处完整）。"""
from app.core.db import Base
from app.models.advice import Advice
from app.models.agent_conversation import AgentConversation
from app.models.annotation import Annotation
from app.models.analysis import Analysis
from app.models.capture_point import CapturePoint
from app.models.crop import Crop
from app.models.device import Device
from app.models.device_event import DeviceEvent
from app.models.device_heartbeat import DeviceHeartbeat
from app.models.dataset_version import DatasetVersion
from app.models.field import Field
from app.models.follow_up import FollowUp
from app.models.model_evaluation import ModelEvaluation
from app.models.patrol import Patrol
from app.models.patrol_report import PatrolReport
from app.models.planting import Planting
from app.models.revisit_task import RevisitTask
from app.models.rule import Rule
from app.models.rule_revision import RuleRevision
from app.models.risk_prediction import RiskPrediction
from app.models.weather import WeatherSample

__all__ = [
    "Base",
    "Advice",
    "AgentConversation",
    "Annotation",
    "Analysis",
    "CapturePoint",
    "Crop",
    "Device",
    "DeviceEvent",
    "DeviceHeartbeat",
    "DatasetVersion",
    "Field",
    "FollowUp",
    "ModelEvaluation",
    "Patrol",
    "PatrolReport",
    "Planting",
    "RevisitTask",
    "Rule",
    "RuleRevision",
    "RiskPrediction",
    "WeatherSample",
]
