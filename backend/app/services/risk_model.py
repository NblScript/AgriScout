"""可训练风险模型（risk-lr-*）：模型文件读写、校验、缓存与区域预测（执行计划 0009）。

模型文件是训练产物，放在 ``RISK_MODEL_DIR``（默认 backend/models/，gitignore，红线 7）。
文件内容带训练目标（目标事件、窗口 H、网格边长、回看天数）：请求的目标与之不符时拒绝，
换了目标的预测不能冠用这个模型的名字。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.logistic import LogisticModel, model_from_dict
from app.services.region_association import parse_key
from app.services.risk_features import image_features, neighbor_map
from app.services.risk_inputs import RegionInputs
from app.services.risk_prediction import RiskThresholds, _trend

MODEL_SCHEMA = "agriscout.risk-model.v1"
LR_PREFIX = "risk-lr-"
# 版本号即文件名：白名单字符，杜绝路径穿越（不含 / 与 \）
_VERSION_RE = re.compile(r"^risk-lr-[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
DEFAULT_LEVEL_RATIOS = {"medium": 2.0, "high": 5.0}


def is_lr_version(version: str) -> bool:
    return version.startswith(LR_PREFIX)


def model_path(version: str, model_dir: str | Path | None = None) -> Path:
    if not _VERSION_RE.match(version) or ".." in version:
        raise ValueError(f"模型版本号不合法：{version!r}（只允许 risk-lr- 开头的字母、数字、点、下划线、连字符）")
    return Path(model_dir or get_settings().risk_model_dir) / f"{version}.json"


def _canonical(doc: dict[str, Any]) -> bytes:
    body = {k: v for k, v in doc.items() if k != "sha256"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def save_model_file(doc: dict[str, Any], path: Path) -> str:
    """写模型文件并返回内容 SHA-256（写入文件本身，加载时校验，防止被手改后仍冒用同一版本号）。"""
    doc = {**doc, "sha256": hashlib.sha256(_canonical(doc)).hexdigest()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc["sha256"]


@dataclass(frozen=True, slots=True)
class RiskModel:
    version: str
    model: LogisticModel
    target_event: str
    horizon_hours: int
    region_cell_m: float
    history_days: int
    prevalence: float
    sha256: str
    level_ratios: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_LEVEL_RATIOS))
    metadata: dict[str, Any] = field(default_factory=dict)

    def level(self, probability: float) -> str:
        """相对风险分级：罕见事件下固定 0.33/0.66 阈值会让所有点都是 low。"""
        if probability >= self.prevalence * self.level_ratios["high"]:
            return "high"
        if probability >= self.prevalence * self.level_ratios["medium"]:
            return "medium"
        return "low"

    def check_request(self, *, target_event: str, forecast_hours: int, cell_m: float, history_days: int) -> None:
        mismatches = []
        if target_event != self.target_event:
            mismatches.append(f"目标事件 {target_event!r} ≠ 训练时 {self.target_event!r}")
        if forecast_hours != self.horizon_hours:
            mismatches.append(f"预测窗口 {forecast_hours}h ≠ 训练时 {self.horizon_hours}h")
        if not math.isclose(cell_m, self.region_cell_m):
            mismatches.append(f"区域网格 {cell_m}m ≠ 训练时 {self.region_cell_m}m")
        if history_days != self.history_days:
            mismatches.append(f"回看 {history_days} 天 ≠ 训练时 {self.history_days} 天")
        if mismatches:
            raise ValueError(f"请求与模型 {self.version} 的训练目标不一致：" + "；".join(mismatches))


def parse_model(doc: dict[str, Any], expected_version: str) -> RiskModel:
    if doc.get("schema") != MODEL_SCHEMA:
        raise ValueError(f"模型文件格式不符：期望 {MODEL_SCHEMA}")
    if doc.get("model_version") != expected_version:
        raise ValueError(f"模型文件里的版本号 {doc.get('model_version')!r} 与文件名 {expected_version!r} 不一致")
    if doc.get("sha256") != hashlib.sha256(_canonical(doc)).hexdigest():
        raise ValueError("模型文件内容与 SHA-256 不符（可能被手工修改），请重新训练导出")
    prevalence = float(doc["prevalence"])
    if not 0 < prevalence < 1:
        raise ValueError("模型的训练患病率必须在 0 与 1 之间")
    return RiskModel(
        version=expected_version,
        model=model_from_dict(doc["model"]),
        target_event=str(doc["target_event"]),
        horizon_hours=int(doc["horizon_hours"]),
        region_cell_m=float(doc["region_cell_m"]),
        history_days=int(doc["history_days"]),
        prevalence=prevalence,
        sha256=doc["sha256"],
        level_ratios={**DEFAULT_LEVEL_RATIOS, **doc.get("level_ratios", {})},
        metadata={k: doc.get(k) for k in ("created_at", "trained_on", "cv", "leave_one_field_out", "limitations")},
    )


_CACHE: dict[Path, tuple[tuple[int, int], RiskModel]] = {}


def load_model(version: str, model_dir: str | Path | None = None) -> RiskModel:
    """按版本号加载模型文件；按修改时间与大小缓存。文件不存在抛 FileNotFoundError，内容不合法抛 ValueError。"""
    path = model_path(version, model_dir)
    try:
        stat = path.stat()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"模型文件不存在：{path}（先运行 python -m app.tools.train_risk_lr 训练导出）"
        ) from None
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"模型文件无法解析：{path}（{exc}）") from exc
    model = parse_model(doc, version)
    _CACHE[path] = (stamp, model)
    return model


@dataclass(frozen=True, slots=True)
class RegionRisk:
    """一个区域在本趟巡检的风险结果（启发式与 risk-lr-* 共用的落库形态）。"""

    probability: float
    level: str
    trend: str
    confidence: float
    evidence: dict[str, Any]


def image_table(inputs: RegionInputs, current_patrol_id: int) -> tuple[dict, list[int], dict[str, tuple[int, int]]]:
    """(区域, 巡检 id) → 区域风险分；更早巡检按时间排序；全部区域的网格坐标。"""
    scores: dict[tuple[str, int], float] = {}
    times: dict[int, Any] = {}
    for key, observations in inputs.history.items():
        for pid, obs in observations:
            if obs.get("risk_score") is not None:
                scores[(key, pid)] = obs["risk_score"]
            times[pid] = min(times.get(pid, obs["captured_at"]), obs["captured_at"])
    for key, series in inputs.series.items():
        if series.current.get("risk_score") is not None:
            scores[(key, current_patrol_id)] = series.current["risk_score"]
    earlier = sorted(times, key=lambda pid: (times[pid], pid))
    regions = {}
    for key in {*inputs.history, *inputs.series}:
        parsed = parse_key(key)
        if parsed is not None:
            regions[key] = (parsed[2], parsed[3])
    return scores, earlier, regions


def predict_regions(
    risk_model: RiskModel, inputs: RegionInputs, current_patrol_id: int, approval: dict[str, Any],
) -> dict[str, RegionRisk]:
    """对本趟巡检每个区域算 risk-lr 概率；特征与离线训练同一实现（risk_features.image_features）。

    approval：该模型版本的审批状态（路由从模型评估表查出），写进 evidence 供追溯。
    """
    scores, earlier, regions = image_table(inputs, current_patrol_id)
    neighbors = neighbor_map(regions)
    rising_delta = RiskThresholds().rising_delta
    results: dict[str, RegionRisk] = {}
    for key, series in inputs.series.items():
        features = image_features(scores, earlier, current_patrol_id, key, neighbors.get(key, []))
        probability = round(risk_model.model.predict(features), 6)
        own = [obs.get("risk_score") for obs in series.observations if obs.get("risk_score") is not None]
        trend, _delta = _trend(own, rising_delta)
        results[key] = RegionRisk(
            probability=probability,
            level=risk_model.level(probability),
            trend=trend,
            confidence=round(abs(2 * probability - 1), 6),
            evidence={
                "model": {
                    "version": risk_model.version, "sha256": risk_model.sha256,
                    "features": list(risk_model.model.names), "prevalence": risk_model.prevalence,
                    "level_rule": f"≥ 患病率×{risk_model.level_ratios['high']:g} 为 high，"
                                  f"≥ ×{risk_model.level_ratios['medium']:g} 为 medium",
                    "confidence_rule": "|2p−1|：概率越接近 0 或 1 越确定",
                    "trained_on": risk_model.metadata.get("trained_on"),
                    "approval": approval,
                },
                "feature_values": {k: round(v, 6) for k, v in features.items()},
                "contributions": _contributions(risk_model.model, features),
            },
        )
    return results


def _contributions(model: LogisticModel, features: dict[str, float]) -> dict[str, float]:
    """各特征对 logit 的贡献（系数 × 标准化值），答辩和复核时解释「为什么说这里有风险」。"""
    return {
        name: round(w * (features[name] - mu) / sd, 4)
        for name, w, mu, sd in zip(model.names, model.weights[1:], model.mean, model.std)
    }
