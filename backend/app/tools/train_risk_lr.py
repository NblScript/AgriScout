"""训练 risk-lr 风险模型并导出模型文件（执行计划 0009）。

用法（数据库取自 DATABASE_URL，与跑模拟季的库相同）：
    cd backend && .venv/bin/python -m app.tools.train_risk_lr \\
        --truth ../simulator/out/season-truth-field1.json --truth ../simulator/out/season-truth-field2.json

特征只用图像/时空 5 项（risk_features.IMAGE_FEATURES，与线上同一实现），暂不含环境特征。
输出 <RISK_MODEL_DIR>/<版本号>.json；已存在同版本号文件时拒绝覆盖（--force 才覆盖）：
一个版本号一旦生成过预测就必须固定不变，否则历史预测对不上号。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.db import SessionLocal
from app.services.evaluation_metrics import average_precision, brier_score
from app.services.logistic import fit_logistic, model_to_dict
from app.services.offline_replay import Sample, build_samples, labeled, out_of_fold
from app.services.region_association import DEFAULT_CELL_M
from app.services.risk_features import DEFAULT_LOOKBACK_DAYS, IMAGE_FEATURES
from app.services.risk_model import MODEL_SCHEMA, model_path, save_model_file
from app.tools.replay_eval import load_input


def _scores(preds: Sequence[float], labels: Sequence[int]) -> dict[str, Any]:
    return {
        "n": len(labels), "positives": sum(labels),
        "pr_auc": average_precision(preds, labels) if sum(labels) else None,
        "brier": brier_score(preds, labels),
    }


def train_risk_model(
    samples_by_field: Mapping[int, Sequence[Sample]],
    *,
    version: str,
    target_event: str,
    horizon_hours: int,
    region_cell_m: float = DEFAULT_CELL_M,
    history_days: int = DEFAULT_LOOKBACK_DAYS,
    names: Sequence[str] = IMAGE_FEATURES,
    sources: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """纯函数：各地块的样本 → 模型文件内容（全量拟合 + 空间条带交叉验证 + 留一块地测试）。"""
    names = tuple(names)
    pooled = [s for field_samples in samples_by_field.values() for s in labeled(field_samples)]
    labels = [s.label for s in pooled]
    positives = sum(labels)
    if not pooled or positives == 0 or positives == len(pooled):
        raise ValueError("训练样本必须同时包含阳性和阴性（首次显症事件太少时无法训练）")
    model = fit_logistic([s.features for s in pooled], labels, names)

    all_samples = [s for field_samples in samples_by_field.values() for s in field_samples]
    oof_all = out_of_fold(all_samples, names)
    oof = [p for s, p in zip(all_samples, oof_all) if s.label is not None]

    leave_one_out = []
    if len(samples_by_field) >= 2:
        for test_field, test_samples in samples_by_field.items():
            train = [s for f, fs in samples_by_field.items() if f != test_field for s in labeled(fs)]
            test = labeled(test_samples)
            held = fit_logistic([s.features for s in train], [s.label for s in train], names)
            leave_one_out.append({
                "test_field_id": test_field,
                **_scores([held.predict(s.features) for s in test], [s.label for s in test]),
            })

    return {
        "schema": MODEL_SCHEMA,
        "model_version": version,
        "target_event": target_event,
        "horizon_hours": horizon_hours,
        "region_cell_m": region_cell_m,
        "history_days": history_days,
        "prevalence": round(positives / len(pooled), 6),
        "level_ratios": {"medium": 2.0, "high": 5.0},
        "model": model_to_dict(model),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trained_on": list(sources) or [
            {"field_id": f, "samples": len(labeled(fs)), "positives": sum(s.label for s in labeled(fs))}
            for f, fs in samples_by_field.items()
        ],
        "cv": {"method": "空间条带分组交叉验证（各地块条带合并）", **_scores(oof, labels)},
        "leave_one_field_out": leave_one_out,
        "limitations": [
            "暂不含环境特征（平台尚无连续气象记录，计划 0007 P0-4）",
            "若训练数据来自模拟器：只检验方法流程，不代表真实病害规律，不能直接用于真实地块决策",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="训练 risk-lr 风险模型（无环境特征）")
    parser.add_argument("--truth", action="append", required=True, help="模拟季真值 JSON，可给多个")
    parser.add_argument("--version", default="risk-lr-v1")
    parser.add_argument("--out-dir", default=None, help="默认 RISK_MODEL_DIR")
    parser.add_argument("--cell-m", type=float, default=DEFAULT_CELL_M)
    parser.add_argument("--history-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--force", action="store_true", help="覆盖已存在的同版本号模型文件")
    args = parser.parse_args(argv)

    try:
        out = model_path(args.version, args.out_dir)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 2
    if out.exists() and not args.force:
        print(f"✗ {out} 已存在：版本号一旦用过就不应改变内容；换一个版本号，或确认后加 --force")
        return 2

    samples_by_field: dict[int, list[Sample]] = {}
    sources, targets = [], set()
    db = SessionLocal()
    try:
        for path in args.truth:
            truth = json.loads(Path(path).read_text(encoding="utf-8"))
            targets.add((truth["target_event"], truth["horizon_hours"]))
            inp = load_input(db, truth, args.cell_m)
            samples = build_samples(inp, lookback_days=args.history_days)
            samples_by_field[truth["field_id"]] = samples
            sources.append({"truth_file": Path(path).name, "field_id": truth["field_id"], "seed": truth.get("seed"),
                            "samples": len(labeled(samples)), "positives": sum(s.label for s in labeled(samples))})
    except ValueError as exc:
        print(f"✗ {exc}")
        return 2
    finally:
        db.close()
    if len(targets) != 1:
        print(f"✗ 真值文件的训练目标不一致：{sorted(targets)}")
        return 2
    target_event, horizon_hours = targets.pop()

    try:
        doc = train_risk_model(
            samples_by_field, version=args.version, target_event=target_event, horizon_hours=horizon_hours,
            region_cell_m=args.cell_m, history_days=args.history_days, sources=sources,
        )
    except ValueError as exc:
        print(f"✗ {exc}")
        return 2
    sha = save_model_file(doc, out)

    print(f"═══ {args.version}：{target_event}，H = {horizon_hours} 小时，特征 {', '.join(IMAGE_FEATURES)} ═══")
    for src in sources:
        print(f"  训练数据 {src['truth_file']}（地块 #{src['field_id']}）：样本 {src['samples']}，阳性 {src['positives']}")
    weights = doc["model"]["weights"]
    print(f"  截距 {weights[0]:+.3f}（训练患病率 {doc['prevalence']:.4f}）")
    for name, w in zip(IMAGE_FEATURES, weights[1:]):
        print(f"  {name:13s} 系数 {w:+.3f}   每升高 1 个标准差，发病几率 ×{math.exp(w):.2f}")
    cv = doc["cv"]
    print(f"  交叉验证：PR-AUC {cv['pr_auc']}，Brier {cv['brier']}（样本 {cv['n']}，阳性 {cv['positives']}）")
    for row in doc["leave_one_field_out"]:
        print(f"  留一块地（测试地块 #{row['test_field_id']}）：PR-AUC {row['pr_auc']}，Brier {row['brier']}"
              f"（样本 {row['n']}，阳性 {row['positives']}）")
    print(f"[模型] {out}\n  SHA-256 {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
