"""离线重放评估（纯函数，不读写数据库）：在全覆盖巡检数据上做申报书 H1–H3 的对照（执行计划 0008）。

- **H1 特征消融**：同一目标（区域在未来 H 内首次显症），用逻辑回归分别训练
  「仅环境 / 仅图像 / 图像+历史 / 全部（含空间邻域）」，按空间条带分组交叉验证，报告 PR-AUC（区域自助法置信区间）、
  Brier、固定误报负担下的召回率；平台线上预测（启发式或已部署的 risk-lr）作为额外参照。
- **H2 复巡策略**：每趟巡检后有相同的定点复查预算（区域数），比较固定路线 / 随机 / 只按风险 / 联合策略
  （平台 ``rank_candidates`` 的 revisit 打分）。定点近距离复查能在更低严重度确认病害；同一区域只计一次。
- **H3 标注选样**：相同初始样本与候选池，比较随机 / 仅不确定性 / 联合策略（平台 label 打分 + 重复惩罚）的学习曲线。

真值（逐日严重度）只用于生成标签和判定「复查能否确认」，绝不进入特征。
局限：同一季内交叉验证偏乐观；正式结论需要跨地块或跨季的独立测试集（申报书 8.3）。
"""
from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.active_learning import (
    ActiveLearningCandidate,
    SelectionConstraints,
    rank_candidates,
    revisit_candidate,
    select_revisits,
)
from app.services.evaluation_metrics import average_precision, brier_score, recall_at_fp_budget
from app.services.logistic import LogisticModel, fit_logistic
from app.services.risk_features import DEFAULT_LOOKBACK_DAYS, IMAGE_FEATURES, image_features, neighbor_map

FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "env": ("env_fav", "env_rain", "env_humidity"),
    "image": ("img_now",),
    "image_history": ("img_now", "img_hist_max", "img_delta"),
    "no_env": IMAGE_FEATURES,
    "full": (*IMAGE_FEATURES, "env_fav", "env_rain", "env_humidity"),
}
FEATURE_SET_LABELS = {
    "env": "仅环境", "image": "仅图像", "image_history": "图像+历史",
    "no_env": "图像+历史+邻域（无环境，risk-lr-v1）", "full": "全部（含空间邻域与环境）",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------- 输入与样本


@dataclass(frozen=True, slots=True)
class ReplayInput:
    patrol_days: list[int]                                  # 升序的巡检日（相对模拟季第 0 天）
    regions: dict[str, tuple[int, int]]                     # 区域键 → 网格坐标 (ix, iy)
    cell_m: float
    image_score: dict[tuple[str, int], float]               # (区域, 巡检日) → 区域内风险分最大值（平台观测）
    truth_severity: dict[str, list[float]]                  # 区域 → 逐日真值严重度（区域内最大）
    weather: list[dict[str, float]]                         # 逐日气象站记录
    horizon_days: int
    platform_prob: dict[tuple[str, int], float] = field(default_factory=dict)
    platform_model: str = "risk-heuristic-v2"                # 平台线上预测所用的模型版本
    event_severity: float = 0.1                             # 首次显症（随访确认）的严重度
    close_severity: float = 0.05                            # 定点近距离复查能确认的严重度
    base_severity: float = 0.3                              # 基础巡检照片稳定可见的严重度

    def severity(self, region: str, day: int) -> float:
        series = self.truth_severity.get(region)
        if not series:
            return 0.0
        return series[min(day, len(series) - 1)]


@dataclass(slots=True)
class Sample:
    """一个区域在一个巡检日的观测。label 为 None 表示该日已显症、不属于首次显症任务（H2 仍要给它打分）。"""

    region: str
    day: int
    fold: int
    features: dict[str, float]
    label: int | None
    platform_p: float | None = None


def _env_features(weather: Sequence[dict[str, float]], day: int) -> dict[str, float]:
    """只用巡检日之前 5 天的气象站记录（当天记录要到日末才完整，不能用）。"""
    past = list(weather[max(0, day - 5): day])
    if not past:
        return {"env_fav": 0.5, "env_rain": 0.0, "env_humidity": 0.5}
    return {
        "env_fav": sum(w["favourability"] for w in past) / len(past),
        "env_rain": _clamp(sum(w["rain_mm"] for w in past) / 30.0),
        "env_humidity": _clamp((sum(w["humidity_pct"] for w in past) / len(past) - 50.0) / 50.0),
    }


def spatial_folds(regions: dict[str, tuple[int, int]], n_folds: int) -> dict[str, int]:
    """沿垄方向（iy）切成 n_folds 个连续条带：相邻区域尽量同组，减少空间自相关泄漏。"""
    rows = sorted({iy for _, iy in regions.values()})
    n = max(1, min(n_folds, len(rows)))
    fold_of_row = {iy: min(n - 1, i * n // len(rows)) for i, iy in enumerate(rows)}
    return {key: fold_of_row[iy] for key, (_, iy) in regions.items()}


def build_samples(
    inp: ReplayInput, n_folds: int = 4, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[Sample]:
    """所有 (区域, 巡检日) 的观测特征；只有巡检日尚未显症的才带标签（窗口 (t, t+H] 内首次显症为阳性）。

    图像/时空特征调用 risk_features.image_features（与线上 risk-lr-* 同一实现，回看窗口一致）；
    环境特征只在离线重放里用（线上暂无连续气象记录）。真值只决定标签，特征与策略打分都读不到。
    """
    neighbors = neighbor_map(inp.regions)
    folds = spatial_folds(inp.regions, n_folds)
    samples: list[Sample] = []
    for k, day in enumerate(inp.patrol_days):
        earlier = [d for d in inp.patrol_days[:k] if d >= day - lookback_days]
        env = _env_features(inp.weather, day)
        for region in sorted(inp.regions):
            label = None if inp.severity(region, day) >= inp.event_severity else int(any(
                inp.severity(region, d) >= inp.event_severity
                for d in range(day + 1, day + inp.horizon_days + 1)
            ))
            features = {**image_features(inp.image_score, earlier, day, region, neighbors[region]), **env}
            samples.append(Sample(region, day, folds[region], features, label,
                                  inp.platform_prob.get((region, day))))
    return samples


# ---------------------------------------------------------------- H1 特征消融


def _bootstrap_ap_ci(
    preds: Sequence[float], labels: Sequence[int], clusters: Sequence[str], reps: int, rng: random.Random,
) -> list[float] | None:
    """按区域整簇重采样的 PR-AUC 95% 置信区间（同一区域多日样本相关，不能逐样本重采样）。"""
    by_cluster: dict[str, list[int]] = {}
    for i, c in enumerate(clusters):
        by_cluster.setdefault(c, []).append(i)
    keys = sorted(by_cluster)
    values = []
    for _ in range(reps):
        idx = [i for k in (rng.choice(keys) for _ in keys) for i in by_cluster[k]]
        ys = [labels[i] for i in idx]
        if sum(ys):
            values.append(average_precision([preds[i] for i in idx], ys))
    if len(values) < reps // 2:
        return None
    values.sort()
    return [round(values[int(0.025 * (len(values) - 1))], 4), round(values[int(0.975 * (len(values) - 1))], 4)]


def _score_block(preds, labels, samples, rng, reps, fp_per_unit) -> dict[str, Any]:
    return {
        "pr_auc": average_precision(preds, labels),
        "pr_auc_ci95": _bootstrap_ap_ci(preds, labels, [s.region for s in samples], reps, rng),
        "brier": brier_score(preds, labels),
        "recall_at_fp": recall_at_fp_budget(preds, labels, [s.day for s in samples], fp_per_unit)["recall"],
    }


def labeled(samples: Sequence[Sample]) -> list[Sample]:
    return [s for s in samples if s.label is not None]


def out_of_fold(
    samples: Sequence[Sample],
    names: Sequence[str],
    labels: Sequence[int | None] | None = None,
    l2: float = 1.0,
) -> list[float]:
    """分组交叉验证：每个观测的预测来自没见过它所在空间条带的模型（只用有标签的观测训练）。

    labels 缺省用首次显症标签（Sample.label）；H2 传入「此刻可被近距离复查确认」的现时标签。
    """
    labels = [s.label for s in samples] if labels is None else list(labels)
    preds = [0.0] * len(samples)
    for fold in sorted({s.fold for s in samples}):
        train = [(s, y) for s, y in zip(samples, labels) if s.fold != fold and y is not None]
        model = fit_logistic([s.features for s, _ in train], [y for _, y in train], names, l2=l2)
        for i, s in enumerate(samples):
            if s.fold == fold:
                preds[i] = model.predict(s.features)
    return preds


def h1_ablation(
    all_samples: Sequence[Sample], *, seed: int = 0, bootstrap: int = 200, fp_per_unit: float = 1.0,
    platform_model: str = "risk-heuristic-v2",
) -> tuple[dict[str, Any], dict[tuple[str, int], float]]:
    """返回 (报告, 全特征模型对所有观测的交叉验证预测)；后者供 H2 的风险排序使用。"""
    samples = labeled(all_samples)
    labels = [s.label for s in samples]
    report: dict[str, Any] = {}
    full_oof: dict[tuple[str, int], float] = {}
    for name, names in FEATURE_SETS.items():
        preds_all = out_of_fold(all_samples, names)
        preds = [p for s, p in zip(all_samples, preds_all) if s.label is not None]
        report[name] = {"label": FEATURE_SET_LABELS[name], "features": list(names),
                        **_score_block(preds, labels, samples, random.Random(seed), bootstrap, fp_per_unit)}
        if name == "full":
            full_oof = {(s.region, s.day): p for s, p in zip(all_samples, preds_all)}
    with_platform = [(s, s.platform_p) for s in samples if s.platform_p is not None]
    if with_platform:
        subset = [s for s, _ in with_platform]
        preds = [p for _, p in with_platform]
        report["platform"] = {
            "label": f"平台线上预测 {platform_model}（不重新训练）", "features": ["platform_probability"],
            "n": len(subset),
            **_score_block(preds, [s.label for s in subset], subset, random.Random(seed), bootstrap, fp_per_unit),
        }
    return report, full_oof


# ---------------------------------------------------------------- H2 复巡策略


def _tour_length(points: Sequence[tuple[float, float]]) -> float:
    """从地头原点出发的最近邻路线长度（米）。"""
    remaining = list(points)
    x, y, total = 0.0, 0.0, 0.0
    while remaining:
        nxt = min(remaining, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
        total += math.hypot(nxt[0] - x, nxt[1] - y)
        x, y = nxt
        remaining.remove(nxt)
    return total


def _snake_order(regions: dict[str, tuple[int, int]]) -> list[str]:
    return sorted(regions, key=lambda k: (regions[k][0], regions[k][1] if regions[k][0] % 2 == 0 else -regions[k][1]))


def h2_revisit_replay(
    inp: ReplayInput,
    samples: Sequence[Sample],
    risk: dict[tuple[str, int], float],
    *,
    budget_frac: float = 0.15,
    flag_score: float = 0.2,
    seed: int = 0,
    random_repeats: int = 20,
) -> dict[str, Any]:
    """每趟巡检后用相同的定点复查预算，比较各策略提前确认病害区域的能力。

    risk 是「此刻有没有近距离可确认的病斑」的现时检出概率（与 H1 的预报目标不同：复查的收益取决于现在，而不是三天后）。

    候选只看平台观测：已确认的区域、以及本趟基础巡检照片已明显异常（区域风险分 ≥ flag_score）
    的区域不再占用复查预算——它们走常规处置流程，复查的价值在于「照片还看不出来」的区域。
    """
    regions = sorted(inp.regions)
    budget = max(1, round(budget_frac * len(regions)))
    last_day = inp.patrol_days[-1]
    interval = (inp.patrol_days[1] - inp.patrol_days[0]) if len(inp.patrol_days) > 1 else 1
    features = {(s.region, s.day): s.features for s in samples}
    route = _snake_order(inp.regions)

    def first_day(region: str, threshold: float) -> int | None:
        return next((d for d in range(last_day + 1) if inp.severity(region, d) >= threshold), None)

    close_day = {r: first_day(r, inp.close_severity) for r in regions}
    base_day = {r: first_day(r, inp.base_severity) for r in regions}
    diseased = [r for r in regions if close_day[r] is not None]

    def centroid(r: str) -> tuple[float, float]:
        ix, iy = inp.regions[r]
        return (ix + 0.5) * inp.cell_m, (iy + 0.5) * inp.cell_m

    def p_of(r: str, day: int, source: dict[tuple[str, int], float]) -> float:
        return source.get((r, day), 0.0)

    def by_score(source: dict[tuple[str, int], float]) -> Callable:
        def choose(cands: list[str], day: int, state: dict) -> list[str]:
            return sorted(cands, key=lambda r: (-p_of(r, day, source), r))[:budget]
        return choose

    def fixed_route(cands: list[str], day: int, state: dict) -> list[str]:
        chosen, pointer, allowed = [], state.setdefault("pointer", 0), set(cands)
        for _ in range(len(route)):
            r = route[pointer % len(route)]
            pointer += 1
            if r in allowed:
                chosen.append(r)
                if len(chosen) == budget:
                    break
        state["pointer"] = pointer
        return chosen

    def joint(cands: list[str], day: int, state: dict) -> list[str]:
        # 候选构造与选择和线上 /revisit-tasks/generate 是同一实现（计划 0015）
        last_visit = state.setdefault("last_visit", {})
        candidates = []
        for r in cands:
            f = features.get((r, day), {})
            candidates.append(revisit_candidate(
                r, probability=p_of(r, day, risk), image_delta=f.get("img_delta", 0.0),
                neighbor_delta=f.get("nbr_delta", 0.0), day=day, last_visit_day=last_visit.get(r),
                interval_days=interval,
            ))
        return [row.candidate_id for row in select_revisits(candidates, budget)]

    def simulate(choose: Callable) -> dict[str, Any]:
        state: dict[str, Any] = {}
        found: dict[str, int] = {}
        visits, travel = 0, 0.0
        for day in inp.patrol_days:
            cands = [r for r in regions if r not in found and inp.image_score.get((r, day), 0.0) < flag_score]
            chosen = choose(cands, day, state)
            visits += len(chosen)
            travel += _tour_length([centroid(r) for r in chosen])
            for r in chosen:
                state.setdefault("last_visit", {})[r] = day
                if inp.severity(r, day) >= inp.close_severity:
                    found[r] = day
        advances = [
            (base_day[r] if base_day[r] is not None else last_day + interval) - d for r, d in found.items()
        ]
        return {
            "found": len(found),
            "found_before_base_visible": sum(1 for r, d in found.items() if inp.severity(r, d) < inp.base_severity),
            "missed_rate": round(1 - len(found) / len(diseased), 4) if diseased else None,
            "found_per_100_visits": round(100 * len(found) / visits, 2) if visits else None,
            "mean_advance_days": round(statistics.mean(advances), 2) if advances else None,
            "visits": visits,
            "travel_m": round(travel, 1),
        }

    def random_pick_seeded(rng_seed: int) -> Callable:
        def choose(cands: list[str], day: int, state: dict) -> list[str]:
            rng = state.setdefault("rng", random.Random(rng_seed))
            return rng.sample(cands, min(budget, len(cands)))
        return choose

    strategies: dict[str, tuple[str, Callable]] = {
        "fixed_route": ("固定路线轮巡", fixed_route),
        "risk_model": ("只按风险（现时检出模型）", by_score(risk)),
        "joint": ("联合策略（平台 revisit 打分）", joint),
    }
    if inp.platform_prob:
        strategies["platform_risk"] = (f"只按风险（平台线上预测 {inp.platform_model}）", by_score(inp.platform_prob))

    report: dict[str, Any] = {
        "budget_per_patrol": budget, "regions": len(regions), "patrols": len(inp.patrol_days),
        "diseased_regions": len(diseased), "flag_score": flag_score, "strategies": {},
    }
    runs = [simulate(random_pick_seeded(seed + k)) for k in range(random_repeats)]
    report["strategies"]["random"] = {
        "label": f"随机抽查（{random_repeats} 次平均）",
        **{
            key: (round(statistics.mean(r[key] for r in runs), 2)
                  if all(r[key] is not None for r in runs) else None)
            for key in runs[0]
        },
    }
    for name, (label, choose) in strategies.items():
        report["strategies"][name] = {"label": label, **simulate(choose)}
    return report


# ---------------------------------------------------------------- H3 标注选样


def h3_active_learning(
    samples: Sequence[Sample],
    *,
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
    init: int = 20,
    step: int = 20,
    budget: int = 160,
    names: Sequence[str] = FEATURE_SETS["full"],
    test_folds: Sequence[int] | None = None,
) -> dict[str, Any]:
    """相同初始样本、相同候选池、相同标注预算下，比较三种选样策略的学习曲线（测试集 PR-AUC）。

    缺省每个 fold 轮流当测试集（空间条带交叉验证）；test_folds 指定固定测试集时只轮这些 fold，
    其余全部作候选池（计划 0011：NWRD 官方测试集）。
    """
    names = tuple(names)
    folds = sorted(test_folds) if test_folds is not None else sorted({s.fold for s in samples})
    strategies = ("random", "uncertainty", "joint")
    curves: dict[str, dict[int, list[float]]] = {s: {} for s in strategies}
    full_aps: list[float] = []

    for fold in folds:
        test = [s for s in samples if s.fold == fold]
        pool = [s for s in samples if s.fold != fold]
        test_labels = [s.label for s in test]
        if not sum(test_labels) or len(pool) <= init:
            continue
        full = fit_logistic([s.features for s in pool], [s.label for s in pool], names)
        full_aps.append(average_precision([full.predict(s.features) for s in test], test_labels))
        for seed in seeds:
            initial = random.Random(seed * 1000 + fold).sample(range(len(pool)), init)
            for strategy in strategies:
                rng = random.Random(seed * 1000 + fold * 10 + strategies.index(strategy))
                labeled = list(initial)
                while True:
                    model = fit_logistic([pool[i].features for i in labeled], [pool[i].label for i in labeled], names)
                    ap = average_precision([model.predict(s.features) for s in test], test_labels)
                    curves[strategy].setdefault(len(labeled), []).append(ap)
                    if len(labeled) >= min(budget, len(pool)):
                        break
                    labeled += _select(strategy, pool, labeled, model, step, rng)

    def mean_curve(strategy: str) -> list[list[float]]:
        return [[n, round(statistics.mean(v), 4)] for n, v in sorted(curves[strategy].items())]

    reference = statistics.mean(full_aps) if full_aps else None
    report: dict[str, Any] = {
        "init": init, "step": step, "budget": budget, "seeds": list(seeds), "folds_used": len(full_aps),
        "full_pool_pr_auc": round(reference, 4) if reference is not None else None,
        "curves": {s: mean_curve(s) for s in strategies},
    }
    report["area_under_curve"] = {
        s: round(statistics.mean(ap for _, ap in report["curves"][s]), 4) if report["curves"][s] else None
        for s in strategies
    }
    for pct in (90, 95):
        report[f"labels_to_{pct}pct_of_full"] = {
            s: next((n for n, ap in report["curves"][s] if reference and ap >= pct / 100 * reference), None)
            for s in strategies
        }
    return report


def _select(strategy: str, pool: Sequence[Sample], labeled: list[int], model: LogisticModel,
            step: int, rng: random.Random) -> list[int]:
    chosen = set(labeled)
    candidates = [i for i in range(len(pool)) if i not in chosen]
    rng.shuffle(candidates)  # 并列时的次序随机化，避免按区域名系统性偏向
    if strategy == "random":
        return candidates[:step]
    probs = {i: model.predict(pool[i].features) for i in candidates}
    if strategy == "uncertainty":
        return sorted(candidates, key=lambda i: abs(2 * probs[i] - 1))[:step]
    # joint：平台 label 打分；代表性 = 特征空间里离已标注样本的距离，已标过的区域打折（重复惩罚）
    vec = {i: [(pool[i].features[n] - mu) / sd for n, mu, sd in zip(model.names, model.mean, model.std)]
           for i in candidates + labeled}
    distance = {i: min(math.dist(vec[i], vec[j]) for j in labeled) for i in candidates}
    top = max(distance.values(), default=0.0) or 1.0
    labeled_regions = {pool[j].region for j in labeled}
    ranked = rank_candidates(
        [
            ActiveLearningCandidate(
                candidate_id=str(i), quality=1.0,
                uncertainty=1 - abs(2 * probs[i] - 1), risk=probs[i],
                # 单日期图像没有时序变化：缺省 0（计划 0011）
                change=_clamp(2 * max(pool[i].features.get("img_delta", 0.0), pool[i].features.get("nbr_delta", 0.0))),
                representativeness=(distance[i] / top) * (0.3 if pool[i].region in labeled_regions else 1.0),
                cost=1.0,
            )
            for i in candidates
        ],
        SelectionConstraints(allowed_task_types=frozenset({"label"})),
    )
    picked, regions = [], set()
    for row in ranked:  # 同一批次每个区域最多取一个样本
        i = int(row.candidate_id)
        if pool[i].region in regions:
            continue
        picked.append(i)
        regions.add(pool[i].region)
        if len(picked) == step:
            break
    return picked


# ---------------------------------------------------------------- 汇总


def run_replay(
    inp: ReplayInput,
    *,
    n_folds: int = 4,
    seed: int = 0,
    revisit_budget_frac: float = 0.15,
    al_seeds: Sequence[int] = (0, 1, 2, 3, 4),
) -> dict[str, Any]:
    all_samples = build_samples(inp, n_folds)
    samples = labeled(all_samples)
    positives = sum(s.label for s in samples)
    h1, _ = h1_ablation(all_samples, seed=seed, platform_model=inp.platform_model)
    nowcast = out_of_fold(
        all_samples, FEATURE_SETS["full"],
        labels=[int(inp.severity(s.region, s.day) >= inp.close_severity) for s in all_samples],
    )
    nowcast_by = {(s.region, s.day): p for s, p in zip(all_samples, nowcast)}
    return {
        "data": {
            "regions": len(inp.regions), "patrols": len(inp.patrol_days), "samples": len(samples),
            "positives": positives, "prevalence": round(positives / len(samples), 4) if samples else None,
            "folds": len({s.fold for s in samples}), "horizon_days": inp.horizon_days,
        },
        "h1": h1,
        "h2": h2_revisit_replay(inp, all_samples, nowcast_by, budget_frac=revisit_budget_frac, seed=seed),
        "h3": h3_active_learning(samples, seeds=al_seeds),
        "limitations": [
            "同一季内按空间条带交叉验证，结果偏乐观；正式结论需要跨地块或跨季的独立测试集",
            "真值来自模拟器，参数未经农学校准，只检验方法流程，不代表真实病害规律",
            "H2 的现时检出模型用交叉验证预测，训练时用到了同季其他条带的标签",
        ],
    }
