"""PatrolReport 巡检 AI 农事报告 DTO。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PatrolReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patrol_id: int
    content: str
    model: str
    prompt_version: str
    input_digest: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ReportGenerateOut(BaseModel):
    patrol_id: int
    report_id: int
    model: str
    prompt_version: str
