"""每株状态（计划 0015，纯函数，不读写数据库）：人工确认优先，没有人工结论时用模型分做占位判断。

状态口径沿用「健康 / 早期 / 明显」三阶段分级（0013 背景，引用农大 / 北大 2026 年论文的口径），另加 unknown：
- 人工：取最近一次带状态含义的标注。只有确认状态用的四个标签算数（normal、downy_mildew_early、
  downy_mildew_symptomatic、other）；dry_stress、suspected_disease 是小麦阶段的标签，不改变每株状态。
- 模型：取最近一张合格叶背图的 risk_score。**WP5 之前这只是占位**：现有分析器不是黄瓜霜霉病模型，
  分数不能当诊断，所以把握程度固定为 0.3。
- 没有任何观测时为 unknown。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.timeutil import to_utc

State = Literal["healthy", "early", "symptomatic", "unknown"]
Source = Literal["human", "model", "none"]

# 确认状态的标签 → 每株状态；other 是人看过但不属于三阶段（例如别的病害），状态记 unknown
HUMAN_LABEL_STATES: dict[str, State] = {
    "normal": "healthy",
    "downy_mildew_early": "early",
    "downy_mildew_symptomatic": "symptomatic",
    "other": "unknown",
}
HUMAN_CONFIDENCE = 1.0


@dataclass(frozen=True)
class PlantStateParams:
    # 模型占位阈值：risk_score ≥ 0.7 记明显、≥ 0.4 记早期（经验初值，WP5 训练出霜霉病模型后按验证集重定）
    early_threshold: float = 0.4
    symptomatic_threshold: float = 0.7
    model_confidence: float = 0.3


DEFAULT_PARAMS = PlantStateParams()


@dataclass(frozen=True)
class Observation:
    captured_at: datetime
    side: str | None  # upper / under / unknown；v1 数据没有视角时为 None
    accepted: bool | None  # 车端或平台的质量结论；都没有时为 None（不算合格）
    risk_score: float | None
    analyzer_version: str | None = None


@dataclass(frozen=True)
class HumanLabel:
    label: str
    at: datetime  # 标注的最近更新时间
    annotator_name: str | None = None


@dataclass(frozen=True)
class PlantState:
    state: State
    source: Source
    confidence: float
    model_score: float | None
    last_seen_at: datetime | None
    last_under_ok_at: datetime | None
    # 最近一张叶背图是否合格（None = 从没拍到叶背）；补拍打分要用
    last_under_accepted: bool | None = None
    reviewed_at: datetime | None = None  # 采用的人工结论的时间
    analyzer_version: str | None = None

    def as_dict(self) -> dict:
        return {
            "state": self.state, "source": self.source, "confidence": self.confidence,
            "model_score": self.model_score, "last_seen_at": self.last_seen_at,
            "last_under_ok_at": self.last_under_ok_at, "last_under_accepted": self.last_under_accepted,
            "reviewed_at": self.reviewed_at, "analyzer_version": self.analyzer_version,
        }


def model_state(score: float, params: PlantStateParams = DEFAULT_PARAMS) -> State:
    if score >= params.symptomatic_threshold:
        return "symptomatic"
    if score >= params.early_threshold:
        return "early"
    return "healthy"


def plant_state(
    observations: Sequence[Observation], labels: Sequence[HumanLabel], params: PlantStateParams = DEFAULT_PARAMS,
) -> PlantState:
    obs = sorted(observations, key=lambda o: to_utc(o.captured_at))
    under = [o for o in obs if o.side == "under"]
    under_ok = [o for o in under if o.accepted is True]
    scored = [o for o in under_ok if o.risk_score is not None]
    latest_scored = scored[-1] if scored else None
    model_score = latest_scored.risk_score if latest_scored is not None else None
    common = {
        "model_score": model_score,
        "last_seen_at": obs[-1].captured_at if obs else None,
        "last_under_ok_at": under_ok[-1].captured_at if under_ok else None,
        "last_under_accepted": under[-1].accepted is True if under else None,
        "analyzer_version": latest_scored.analyzer_version if latest_scored is not None else None,
    }
    human = [h for h in labels if h.label in HUMAN_LABEL_STATES]
    if human:
        latest = max(human, key=lambda h: to_utc(h.at))
        return PlantState(state=HUMAN_LABEL_STATES[latest.label], source="human", confidence=HUMAN_CONFIDENCE,
                          reviewed_at=latest.at, **common)
    if model_score is not None:
        return PlantState(state=model_state(model_score, params), source="model",
                          confidence=params.model_confidence, **common)
    return PlantState(state="unknown", source="none", confidence=0.0, **common)
