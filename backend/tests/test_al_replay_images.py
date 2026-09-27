"""H3 真实数据验证工具（计划 0011）：样本文件读取、候选池抽稀、配对差与逐种子运行。"""
import random

import pytest

from app.services.offline_replay import Sample
from app.tools.al_replay_images import SCHEMA, load_samples, paired_diff, run, thin_positives


def _doc(n_pool=300, n_test=80, seed=0):
    rng = random.Random(seed)
    rows = []
    for i in range(n_pool + n_test):
        label = int(rng.random() < 0.33)
        rows.append({"region": f"img{i % 20}", "fold": 0 if i < n_test else 1, "label": label,
                     "features": [rng.gauss(1.4 if label else 0.0, 1.0), rng.gauss(0, 1)]})
    return {"schema": SCHEMA, "names": ["pc00", "pc01"], "test_fold": 0, "samples": rows,
            "source": {"name": "test", "doi": "x"}, "embedding_model": "test", "pca": {"dims": 2}}


def test_load_rejects_wrong_schema():
    with pytest.raises(ValueError, match="格式不符"):
        load_samples({**_doc(), "schema": "other"})


def test_thin_positives_hits_prevalence_and_keeps_test_and_negatives():
    samples, _ = load_samples(_doc())
    thinned = thin_positives(samples, 0, 0.05, seed=1)
    pool = [s for s in thinned if s.fold != 0]
    assert abs(sum(s.label for s in pool) / len(pool) - 0.05) < 0.01
    assert [s for s in thinned if s.fold == 0] == [s for s in samples if s.fold == 0]
    assert sum(1 - s.label for s in pool) == sum(1 - s.label for s in samples if s.fold != 0)
    assert thinned == thin_positives(samples, 0, 0.05, seed=1)  # 固定种子可复现
    with pytest.raises(ValueError, match="阳性不够"):
        thin_positives(samples, 0, 0.9, seed=1)


def test_paired_diff_ci_brackets_mean():
    d = paired_diff([0.6, 0.62, 0.58, 0.61], [0.5, 0.55, 0.52, 0.5])
    assert d["wins"] == 4 and d["seeds"] == 4
    assert d["ci95"][0] <= d["mean"] <= d["ci95"][1] and d["ci95"][0] > 0


def test_run_reports_per_seed_and_match_budget():
    samples, names = load_samples(_doc())
    report = run(samples, names, 0, seeds=2, init=10, step=10, budget=30)
    assert set(report["per_seed_auc"]) == {"random", "uncertainty", "joint"}
    assert all(len(v) == 2 for v in report["per_seed_auc"].values())
    assert report["labels_to_match_random_at_budget"]["random"] <= 30
    assert set(report["auc_vs_random"]) == {"uncertainty", "joint"}
    assert isinstance(samples[0], Sample)
