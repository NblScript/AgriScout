"""盲法复核接口 DTO（计划 0007 P1-9，决策 D25）。判读接口只给照片，不带株号、模型输出、来源和别人的判读。"""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BlindLabel = Literal["normal", "downy_mildew_early", "downy_mildew_symptomatic", "other"]


class BlindReviewCreate(BaseModel):
    field_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    date_from: date
    date_to: date
    sample_size: int = Field(default=40, ge=0, le=500)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    # 固定参考株：范围内这些株的合格照片全部入批
    reference_keys: list[str] = Field(default_factory=list, max_length=200)
    side: Literal["under", "any"] = "under"
    double_review: bool = True


class BlindReviewSummary(BaseModel):
    status_counts: dict[str, int]
    resolved: int
    pairs: int
    agreement: float | None
    kappa: float | None
    final_labels: dict[str, dict[str, int]]
    my_votes: int | None


class BlindReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field_id: int
    name: str
    status: str
    seed: int
    params: dict[str, Any]
    item_count: int
    created_by: str
    done_at: datetime | None
    created_at: datetime
    summary: BlindReviewSummary


class BlindReviewTask(BaseModel):
    """判读一张：只有照片、第几张和轮次；二次判读另给前两次的判读（不含判读人）。"""

    batch_id: int
    item_id: int
    position: int
    item_count: int
    round: int
    photo_url: str | None
    prior_labels: list[str]


class BlindVoteIn(BaseModel):
    label: BlindLabel


class BlindVoteOut(BaseModel):
    item_id: int
    recorded: bool = True


class BlindResultOut(BaseModel):
    """逐张结论，带株号和拍摄时间：批次全部定论后才给，免得判读中途看到别人的结论。"""

    position: int
    item_id: int
    capture_point_id: int
    patrol_id: int
    observation_key: str | None
    captured_at: datetime
    photo_url: str | None
    origin: str
    status: str
    final_label: str
    annotation_id: int | None
