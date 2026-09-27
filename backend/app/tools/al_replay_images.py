"""H3 真实数据验证 CLI（执行计划 0011）：图像样本文件 → 与仿真相同的 H3 选样对比。

样本文件由 ml/al_features_nwrd.py 导出（NWRD 图块的冻结特征）；fold 0 为官方测试集，其余为候选池。
学习器、三种选样策略（随机 / 仅不确定性 / 联合策略）与仿真 H3 完全相同，见 services/offline_replay.h3_active_learning。
逐种子运行，报告均值学习曲线、曲线下面积相对随机的配对差（自助法 95% 置信区间），以及
「达到随机选样在预算处性能所需的标注数」。--pool-prevalence 把候选池的锈病抽稀到指定比例，模拟田间罕见发病。

用法：
    cd backend && .venv/bin/python -m app.tools.al_replay_images --samples ../ml/data/nwrd_cls/al_features.json
    cd backend && .venv/bin/python -m app.tools.al_replay_images --samples ... --pool-prevalence 0.05
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

from app.services.offline_replay import Sample, h3_active_learning

SCHEMA = "agriscout.al-image-samples.v1"
STRATEGIES = ("random", "uncertainty", "joint")
NAMES = {"random": "随机选样", "uncertainty": "仅不确定性", "joint": "联合策略（平台 label 打分）"}


def load_samples(doc: dict[str, Any]) -> tuple[list[Sample], list[str]]:
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"样本文件格式不符：期望 {SCHEMA}")
    names = list(doc["names"])
    samples = [
        Sample(region=row["region"], day=0, fold=int(row["fold"]),
               features=dict(zip(names, row["features"])), label=int(row["label"]))
        for row in doc["samples"]
    ]
    return samples, names


def thin_positives(samples: list[Sample], test_fold: int, prevalence: float, seed: int) -> list[Sample]:
    """候选池阳性按固定种子抽稀到 prevalence（阴性全保留）；测试集不动。"""
    if not 0 < prevalence < 1:
        raise ValueError("pool_prevalence 必须在 0 到 1 之间")
    test = [s for s in samples if s.fold == test_fold]
    neg = [s for s in samples if s.fold != test_fold and s.label == 0]
    pos = [s for s in samples if s.fold != test_fold and s.label == 1]
    k = round(prevalence / (1 - prevalence) * len(neg))
    if k > len(pos):
        raise ValueError(f"阳性不够：需要 {k}，候选池只有 {len(pos)}")
    return test + neg + random.Random(seed).sample(pos, k)


def paired_diff(a: list[float], b: list[float], seed: int = 0, reps: int = 5000) -> dict[str, float]:
    diffs = [x - y for x, y in zip(a, b)]
    rng = random.Random(seed)
    boots = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(reps))
    return {"mean": round(statistics.mean(diffs), 4), "ci95": [round(boots[int(0.025 * reps)], 4),
            round(boots[int(0.975 * reps) - 1], 4)], "wins": sum(d > 0 for d in diffs), "seeds": len(diffs)}


def run(samples: list[Sample], names: list[str], test_fold: int, *, seeds: int, init: int, step: int,
        budget: int) -> dict[str, Any]:
    per_seed = {s: [] for s in STRATEGIES}
    curves: dict[str, dict[int, list[float]]] = {s: {} for s in STRATEGIES}
    full = []
    for seed in range(seeds):
        r = h3_active_learning(samples, seeds=(seed,), init=init, step=step, budget=budget,
                               names=names, test_folds=(test_fold,))
        full.append(r["full_pool_pr_auc"])
        for s in STRATEGIES:
            per_seed[s].append(r["area_under_curve"][s])
            for n, ap in r["curves"][s]:
                curves[s].setdefault(n, []).append(ap)
    mean_curves = {s: [[n, round(statistics.mean(v), 4)] for n, v in sorted(c.items())] for s, c in curves.items()}
    reference = statistics.mean(full)
    target = mean_curves["random"][-1][1]  # 随机选样在预算处的性能
    return {
        "init": init, "step": step, "budget": budget, "seeds": seeds,
        "full_pool_pr_auc": round(reference, 4),
        "curves": mean_curves,
        "area_under_curve": {s: round(statistics.mean(v), 4) for s, v in per_seed.items()},
        "auc_vs_random": {s: paired_diff(per_seed[s], per_seed["random"]) for s in ("uncertainty", "joint")},
        "labels_to_90pct_of_full": {s: next((n for n, ap in mean_curves[s] if ap >= 0.9 * reference), None)
                                    for s in STRATEGIES},
        "labels_to_match_random_at_budget": {s: next((n for n, ap in mean_curves[s] if ap >= target), None)
                                             for s in STRATEGIES},
        "per_seed_auc": per_seed,
    }


def _fmt(value: Any) -> str:
    return "—" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))


def print_report(report: dict[str, Any]) -> None:
    c = report["condition"]
    print(f"数据：{c['data']}；特征 {c['embedding_model']}，PCA {c['pca_dims']} 维")
    print(f"候选池 {c['pool_size']} 块（锈病 {c['pool_positives']}，比例 {c['pool_prevalence']:.3f}），测试集 {c['test_size']} 块；"
          f"初始 {report['init']}，每轮 +{report['step']}，预算 {report['budget']}，{report['seeds']} 个种子；"
          f"全量候选池 PR-AUC {_fmt(report['full_pool_pr_auc'])}")
    counts = [n for n, _ in report["curves"]["random"]]
    print("| 策略 | 曲线下面积 | 相对随机（95% CI，胜出种子） | 达到随机@预算 | " + " | ".join(str(n) for n in counts) + " |")
    for s in STRATEGIES:
        vs = report["auc_vs_random"].get(s)
        rel = f"{vs['mean']:+.3f}（{vs['ci95'][0]:+.3f} ~ {vs['ci95'][1]:+.3f}，{vs['wins']}/{vs['seeds']}）" if vs else "—"
        print(f"| {NAMES[s]} | {_fmt(report['area_under_curve'][s])} | {rel} | "
              f"{_fmt(report['labels_to_match_random_at_budget'][s])} | "
              + " | ".join(_fmt(ap) for _, ap in report["curves"][s]) + " |")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="H3 真实数据验证（图像样本文件）")
    ap.add_argument("--samples", required=True)
    ap.add_argument("--pool-prevalence", type=float, default=None, help="把候选池锈病抽稀到该比例（缺省不抽稀）")
    ap.add_argument("--subsample-seed", type=int, default=123)
    ap.add_argument("--init", type=int, default=20)
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--budget", type=int, default=200)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--out", default=None, help="报告 JSON（缺省与样本文件同目录）")
    args = ap.parse_args(argv)

    path = Path(args.samples)
    doc = json.loads(path.read_text(encoding="utf-8"))
    try:
        samples, names = load_samples(doc)
        if args.pool_prevalence is not None:
            samples = thin_positives(samples, doc["test_fold"], args.pool_prevalence, args.subsample_seed)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 2
    pool = [s for s in samples if s.fold != doc["test_fold"]]
    report = run(samples, names, doc["test_fold"], seeds=args.seeds, init=args.init, step=args.step, budget=args.budget)
    report["condition"] = {
        "data": doc["source"]["name"], "doi": doc["source"]["doi"], "embedding_model": doc["embedding_model"],
        "pca_dims": doc["pca"]["dims"], "pool_size": len(pool), "pool_positives": sum(s.label for s in pool),
        "pool_prevalence": round(sum(s.label for s in pool) / len(pool), 4), "test_size": len(samples) - len(pool),
        "thinned_to": args.pool_prevalence, "subsample_seed": args.subsample_seed if args.pool_prevalence else None,
    }
    print_report(report)
    tag = f"prev{args.pool_prevalence:g}-s{args.subsample_seed}" if args.pool_prevalence else "natural"
    out = Path(args.out) if args.out else path.with_name(f"{path.stem}.h3-{tag}.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[报告] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
