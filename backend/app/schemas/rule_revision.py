"""RuleRevision 规则修订案 DTO（规则线 L1）。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field as PField


class RevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_key: str
    action: str
    draft: dict[str, Any]
    reason: str
    shadow_result: dict[str, Any] | None = None
    status: str
    decided_by: str | None = None
    decide_note: str | None = None
    model: str
    prompt_version: str
    applied_version: int | None = None
    created_at: datetime


class RevisionDecideIn(BaseModel):
    decided_by: str = PField(min_length=1, max_length=80)
    note: str | None = None


class DraftGenerateOut(BaseModel):
    created: int
    revision_ids: list[int]
