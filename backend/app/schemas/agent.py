"""Agent 诊断问答 DTO（建议线 L2）。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field as PField


class AgentChatIn(BaseModel):
    question: str = PField(min_length=1, max_length=4000)
    patrol_id: int | None = None


class AgentChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patrol_id: int | None = None
    question: str
    answer: str
    tool_calls_trace: list[dict[str, Any]]
    model: str
    prompt_version: str
    created_at: datetime
