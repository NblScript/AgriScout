"""离线重放评估 CLI：平台数据库 + 模拟季真值 JSON → H1/H2/H3 对照报告（执行计划 0008）。

用法（数据库取自 DATABASE_URL，与平台同一个库）：
    cd backend && .venv/bin/python -m app.tools.replay_eval --truth ../simulator/out/season-truth-field1.json

特征只来自平台数据（逐点分析、平台预测）与气象站记录；真值严重度只用于生成标签和判定复查结果。
将来真实数据用随访结论替换真值文件即可，评估逻辑在 services/offline_replay.py，不依赖模拟器。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import Analysis, CapturePoint, Field, RiskPrediction
from app.services.offline_replay import ReplayInput, run_replay
from app.services.region_association import DEFAULT_CELL_M, FieldGrid

TRUTH_SCHEMA = "agriscout.season-truth.v1"


def load_input(db: Session, truth: dict[str, Any], cell_m: float = DEFAULT_CELL_M) -> ReplayInput:
    if truth.get("schema") != TRUTH_SCHEMA:
        raise ValueError(f"真值文件格式不符：期望 {TRUTH_SCHEMA}")
    field = db.get(Field, truth["field_id"])
    if field is None:
        raise ValueError(f"数据库里没有地块 #{truth['field_id']}：确认 DATABASE_URL 指向跑模拟季的库")
    grid = FieldGrid.from_boundary(field.id, field.boundary, cell_m)
    patrol_day = {p["patrol_id"]: p["day"] for p in truth["patrols"]}

    regions: dict[str, tuple[int, int]] = {}
    seq_region: dict[int, str] = {}
    point_region: dict[int, tuple[str, int]] = {}
    image_score: dict[tuple[str, int], float] = {}
    rows = db.execute(
        select(CapturePoint, Analysis)
        .outerjoin(Analysis, Analysis.capture_point_id == CapturePoint.id)
        .where(CapturePoint.patrol_id.in_(patrol_day))
    ).all()
    for point, analysis in rows:
        cell = grid.cell(point.lng, point.lat)
        key = grid.key_of_cell(*cell)
        day = patrol_day[point.patrol_id]
        regions[key] = cell
        seq_region[point.seq] = key
        point_region[point.id] = (key, day)
        if analysis is not None and analysis.risk_score is not None:
            image_score[(key, day)] = max(image_score.get((key, day), 0.0), analysis.risk_score)

    truth_severity: dict[str, list[float]] = {}
    for seq, series in truth["severity"].items():
        key = seq_region.get(int(seq))
        if key is None:
            continue
        current = truth_severity.setdefault(key, [0.0] * len(series))
        truth_severity[key] = [max(a, b) for a, b in zip(current, series)]

    platform_prob: dict[tuple[str, int], float] = {}
    predictions = db.scalars(select(RiskPrediction).where(
        RiskPrediction.patrol_id.in_(patrol_day),
        RiskPrediction.target_event == truth["target_event"],
        RiskPrediction.model_version == truth["model_version"],
    ))
    for pred in predictions:
        slot = point_region.get(pred.capture_point_id)
        if slot is not None:
            platform_prob[slot] = max(platform_prob.get(slot, 0.0), pred.probability)

    return ReplayInput(
        patrol_days=sorted(set(patrol_day.values())),
        regions=regions,
        cell_m=cell_m,
        image_score=image_score,
        truth_severity=truth_severity,
        weather=truth["weather"],
        horizon_days=math.ceil(truth["horizon_hours"] / 24),
        platform_prob=platform_prob,
        platform_model=truth["model_version"],
        event_severity=truth["event_severity"],
        base_severity=truth.get("base_detect_severity", 0.3),
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, list):
        return f"[{', '.join(_fmt(v) for v in value)}]"
    return str(value)


def print_report(report: dict[str, Any]) -> None:
    d = report["data"]
    print(f"═══ 数据 ═══\n  区域 {d['regions']}，巡检 {d['patrols']} 趟，样本 {d['samples']}"
          f"（阳性 {d['positives']}，患病率 {_fmt(d['prevalence'])}），H = {d['horizon_days']} 天，空间条带 {d['folds']} 组")

    print("\n═══ H1 特征消融：首次显症，按空间条带分组交叉验证 ═══")
    print("  | 特征组 | PR-AUC | 95% 置信区间 | Brier | 召回率（每日误报≤1） |")
    for row in report["h1"].values():
        print(f"  | {row['label']} | {_fmt(row['pr_auc'])} | {_fmt(row['pr_auc_ci95'])} | "
              f"{_fmt(row['brier'])} | {_fmt(row['recall_at_fp'])} |")

    h2 = report["h2"]
    print(f"\n═══ H2 复巡策略：每趟巡检后定点复查 {h2['budget_per_patrol']} 个区域"
          f"（共 {h2['regions']} 个，季内出现病害 {h2['diseased_regions']} 个）═══")
    print("  | 策略 | 确认病害区域 | 早于基础巡检可见 | 漏查率 | 每百次复查确认 | 平均提前（天） | 路程（米） |")
    for row in h2["strategies"].values():
        print(f"  | {row['label']} | {row['found']} | {row['found_before_base_visible']} | "
              f"{_fmt(row['missed_rate'])} | {_fmt(row['found_per_100_visits'])} | "
              f"{_fmt(row['mean_advance_days'])} | {_fmt(row['travel_m'])} |")

    h3 = report["h3"]
    print(f"\n═══ H3 标注选样：初始 {h3['init']}，每轮 +{h3['step']}，预算 {h3['budget']}；"
          f"{h3['folds_used']} 个测试条带 × {len(h3['seeds'])} 个种子；全量候选池 PR-AUC {_fmt(h3['full_pool_pr_auc'])} ═══")
    names = {"random": "随机", "uncertainty": "仅不确定性", "joint": "联合策略（平台 label 打分）"}
    counts = [n for n, _ in next(iter(h3["curves"].values()), [])]
    print("  | 策略 | 曲线下面积 | 达到全量 90% 所需标注 | " + " | ".join(str(n) for n in counts) + " |")
    for key, curve in h3["curves"].items():
        print(f"  | {names[key]} | {_fmt(h3['area_under_curve'][key])} | "
              f"{_fmt(h3['labels_to_90pct_of_full'][key])} | " + " | ".join(_fmt(ap) for _, ap in curve) + " |")

    print("\n局限：\n" + "\n".join(f"  - {item}" for item in report["limitations"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线重放评估（H1/H2/H3）")
    parser.add_argument("--truth", required=True, help="simulator/season.py 导出的真值 JSON")
    parser.add_argument("--cell-m", type=float, default=DEFAULT_CELL_M, help="区域网格边长（米）")
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--revisit-budget", type=float, default=0.15, help="每趟复查的区域比例")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default=None, help="报告 JSON 路径（默认与真值同目录）")
    args = parser.parse_args(argv)

    truth_path = Path(args.truth)
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        inp = load_input(db, truth, args.cell_m)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 2
    finally:
        db.close()
    report = run_replay(inp, n_folds=args.folds, seed=args.seed, revisit_budget_frac=args.revisit_budget)
    report["source"] = {"truth": str(truth_path), "field_id": truth["field_id"], "seed": truth.get("seed"),
                        "cell_m": args.cell_m}
    print_report(report)
    out = Path(args.out) if args.out else truth_path.with_suffix(".replay.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[报告] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
