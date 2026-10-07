"""大棚巡检策略离线比较（计划 0017，纯函数，不读写数据库）。

读 ``simulator/greenhouse_run.py`` 导出的真值（``agriscout.greenhouse-truth.v1``），在同一份真值上逐日跑巡检策略：

- **fixed**：每 k 天全覆盖一次（滚动：每天拍 1/k 的株，正面、叶背各一张），不补拍；人工从当天拍过的株里随机抽 H 株确认。
  两个对照变体把作用拆开：``fixed_morning`` 只把拍摄挪到清晨（看时段的作用）；``fixed_ranked`` 照片照旧，
  人工改看 planner 的确认名单（看「按模型分派人工」的作用，剩下的差别才是拍哪些株）。
- **risk**：每天调用 0015 的 ``patrol_planner.build_plan``（与线上同一份实现，输入也走 ``greenhouse_plans.planner_inputs``），
  有清晨窗口就清晨拍；按 补拍 > 全覆盖 > 抽查 的顺序拍到照片上限，叶背不合格就重拍；人工确认计划的确认名单。

各策略每天的照片上限 C 和人工确认上限 H 相同。照片合格与否、看不看得出病斑按真值里的可见性参数抽样；
同一株、同一天、同一视角、第几次拍，在不同策略里用同一组随机数（共同随机数），差异只来自策略本身。
人工结论的规则与模拟器相同：最近一张看得出病斑的合格照片决定结论，再按误判率翻转（模拟器与后端各实现一份，红线 6）。

**模拟结论只证明流程**：病害规律和可见性是按设计放进模拟器的（D5），数字不能当作效果证据。
"""
from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from app.core.timeutil import FIELD_TZ
from app.services import greenhouse_env, greenhouse_plans, patrol_planner
from app.services.plant_state import HumanLabel, Observation, plant_state

TRUTH_SCHEMA = "agriscout.greenhouse-truth.v1"
REPORT_VERSION = "gh-replay-v1"
DISCLAIMER = "模拟结论只证明流程：病害规律与可见性参数都是设计假设（D5），下面的数字不能当作效果证据。"
STRATEGIES = ("fixed", "fixed_morning", "fixed_ranked", "risk")
STRATEGY_TITLES = {"fixed": "固定巡检", "fixed_morning": "固定巡检·清晨拍", "fixed_ranked": "固定巡检·按模型分确认",
                   "risk": "风险驱动（planner-v0）"}
SHOOT_TIME = {"morning": time(6, 30), "day": time(10, 0)}
SECONDS_PER_SHOT = 15
CONFIRM_TIME = time(14, 0)
STATE_CODES = {"H": "healthy", "L": "latent", "E": "early", "S": "symptomatic"}
TRUE_LABEL = {"healthy": "normal", "latent": "normal", "early": "downy_mildew_early",
              "symptomatic": "downy_mildew_symptomatic"}
CONFIRM_LABELS = ("normal", "downy_mildew_early", "downy_mildew_symptomatic")
POSITIVE_LABELS = ("downy_mildew_early", "downy_mildew_symptomatic")
ENV_HISTORY_DAYS = 7  # 与 greenhouse_plans.generate_plan 取环境摘要的天数一致


@dataclass(frozen=True)
class ReplayParams:
    fixed_every_days: int = 3  # fixed 的全覆盖周期 k
    human_budget: int = 5  # 每天人工确认上限 H（risk 的 planner 也用它）
    photo_cap: int | None = None  # 每天照片上限 C；None = ceil(2 × 株数 / k)，即 fixed 正好用满
    strategies: tuple[str, ...] = STRATEGIES

    def __post_init__(self) -> None:
        if self.fixed_every_days < 1 or self.human_budget < 0 or (self.photo_cap is not None and self.photo_cap < 1):
            raise ValueError("全覆盖周期至少 1 天，人工预算不能为负，照片上限至少 1")
        unknown = [s for s in self.strategies if s not in STRATEGIES]
        if unknown or not self.strategies:
            raise ValueError(f"策略只能取 {STRATEGIES}")

    def cap_for(self, n_plants: int) -> int:
        return self.photo_cap if self.photo_cap is not None else math.ceil(2 * n_plants / self.fixed_every_days)


# ---------------------------------------------------------------- 真值


@dataclass(frozen=True)
class TruthPlant:
    key: str
    row: int
    pos: int
    infected_hour: int | None
    early_hour: int | None
    symptomatic_hour: int | None

    def state_at(self, hour: int) -> str:
        if self.infected_hour is None or hour < self.infected_hour:
            return "healthy"
        if hour < self.early_hour:
            return "latent"
        if hour < self.symptomatic_hour:
            return "early"
        return "symptomatic"


@dataclass
class Truth:
    seed: int
    facility_type: str
    day0: date
    days: int
    extra_days: int
    state_hour: int
    readings: list[greenhouse_env.Reading]
    plants: list[TruthPlant]  # 按株号排序
    visibility: dict[str, Any]
    photo_scores: dict[str, float]
    human_error: float
    layout: dict[str, Any] = field(default_factory=dict)

    def state(self, plant: TruthPlant, day: int) -> str:
        return plant.state_at(day * 24 + self.state_hour)

    def first_day(self, plant: TruthPlant, states: Sequence[str]) -> int | None:
        """第一天（每天 state_hour 点）处于 states 之一；季后也查，查不到为 None。"""
        for day in range(self.days + self.extra_days):
            if self.state(plant, day) in states:
                return day
        return None

    def at(self, day: int, clock: time) -> datetime:
        return datetime.combine(self.day0 + timedelta(days=day), clock, tzinfo=FIELD_TZ)


def load_truth(data: dict[str, Any]) -> Truth:
    if data.get("schema") != TRUTH_SCHEMA:
        raise ValueError(f"真值文件格式不符：期望 {TRUTH_SCHEMA}，由 simulator/greenhouse_run.py 导出")
    plants = sorted((TruthPlant(p["key"], p["row"], p["pos"], p.get("infected_hour"), p.get("early_hour"),
                                p.get("symptomatic_hour")) for p in data["plants"]), key=lambda p: p.key)
    readings = [greenhouse_env.Reading(datetime.fromisoformat(h["at"]), h["temp_c"], h["humidity_pct"])
                for h in data["env_hourly"]]
    return Truth(
        seed=int(data["seed"]), facility_type=data["facility_type"], day0=date.fromisoformat(data["day0"]),
        days=int(data["days"]), extra_days=int(data.get("extra_days", 0)), state_hour=int(data.get("state_hour", 8)),
        readings=sorted(readings, key=lambda r: r.observed_at), plants=plants, visibility=data["visibility"],
        photo_scores=data["photo_scores"], human_error=float(data.get("human_error", 0.0)),
        layout=data.get("layout") or {},
    )


# ---------------------------------------------------------------- 拍照与人工确认


@dataclass(frozen=True)
class Photo:
    key: str
    day: int
    side: str
    period: str
    attempt: int
    accepted: bool
    detected: bool
    state: str
    score: float
    captured_at: datetime


@dataclass(frozen=True)
class Confirmation:
    key: str
    day: int
    label: str
    truth_state: str  # 确认当天的真值状态


def _draws(seed: int, key: str, day: int, side: str, attempt: int) -> tuple[float, float]:
    """共同随机数：(合格抽样, 检出抽样) 只由 种子、株、天、视角、第几次 决定，与策略无关。"""
    rng = random.Random(f"gh-replay:{seed}:{key}:{day}:{side}:{attempt}")
    return rng.random(), rng.random()


def take_photo(truth: Truth, plant: TruthPlant, day: int, side: str, period: str, attempt: int,
               at: datetime) -> Photo:
    vis = truth.visibility
    state = truth.state(plant, day)
    ok_prob = 1.0 - vis["reject"][side] if attempt == 1 else vis["reshoot_success"]
    u_ok, u_detect = _draws(truth.seed, plant.key, day, side, attempt)
    accepted = u_ok < ok_prob
    detected = accepted and u_detect < vis["detect"][state][side][period]
    band = "none" if not detected else (state if state in ("early", "symptomatic") else "false_positive")
    return Photo(plant.key, day, side, period, attempt, accepted, detected, state, truth.photo_scores[band], at)


def human_confirm(truth: Truth, plant: TruthPlant, day: int, photos: Sequence[Photo]) -> Confirmation:
    """人看这株最近的合格叶背图和合格正面图下结论（与 simulator/greenhouse.py 的 human_label 同一规则）。"""
    ok = [p for p in photos if p.accepted]
    seen = [p for side in ("under", "upper") for p in [next((q for q in reversed(ok) if q.side == side), None)] if p]
    seen.sort(key=lambda p: p.captured_at)
    label = "normal"
    for photo in reversed(seen):
        if photo.detected:
            label = TRUE_LABEL[photo.state]
            break
    rng = random.Random(f"gh-replay:{truth.seed}:human:{plant.key}:{day}")
    if rng.random() < truth.human_error:
        label = rng.choice([x for x in CONFIRM_LABELS if x != label])
    return Confirmation(plant.key, day, label, truth.state(plant, day))


class _Camera:
    """一天的拍照：按顺序拍，到照片上限就停。"""

    def __init__(self, truth: Truth, day: int, period: str, cap: int, max_attempts: int) -> None:
        self.truth, self.day, self.period, self.cap, self.max_attempts = truth, day, period, cap, max_attempts
        self.start = truth.at(day, SHOOT_TIME[period])
        self.photos: list[Photo] = []

    def shoot(self, plant: TruthPlant, side: str, *, reshoot: bool) -> list[Photo]:
        taken = []
        for attempt in range(1, (self.max_attempts if reshoot else 1) + 1):
            if len(self.photos) >= self.cap:
                break
            at = self.start + timedelta(seconds=len(self.photos) * SECONDS_PER_SHOT)
            photo = take_photo(self.truth, plant, self.day, side, self.period, attempt, at)
            self.photos.append(photo)
            taken.append(photo)
            if photo.accepted:
                break
        return taken


# ---------------------------------------------------------------- 策略


@dataclass
class _SimUnit:
    """planner_inputs 需要的株档案字段（id / key / row_no / position_no）。"""

    id: int
    key: str
    row_no: int
    position_no: int


@dataclass
class StrategyRun:
    strategy: str
    photo_cap: int
    human_budget: int
    daily_photos: list[int] = field(default_factory=list)
    daily_confirms: list[int] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    confirmations: list[Confirmation] = field(default_factory=list)
    planner_calls: int = 0


def _observation(photo: Photo) -> Observation:
    return Observation(photo.captured_at, photo.side, photo.accepted, photo.score, "sim-photo-scores")


def plan_for_day(truth: Truth, day: int, history: dict[str, list[Photo]], labels: dict[str, list[HumanLabel]],
                 params: patrol_planner.PlannerParams) -> dict[str, Any]:
    """与 greenhouse_plans.generate_plan 同口径：截止计划日当地 08:00，环境取前 7 天，抽查种子按（种子, 计划日）。"""
    plan_date = truth.day0 + timedelta(days=day)
    as_of = truth.at(day, greenhouse_plans.PLAN_ENV_CUTOFF)
    since = as_of - timedelta(days=ENV_HISTORY_DAYS)
    readings = [r for r in truth.readings if since <= r.observed_at < as_of]
    summary = greenhouse_env.summarize(readings, as_of, plan_date, history_days=ENV_HISTORY_DAYS)
    contexts = []
    for idx, plant in enumerate(truth.plants, start=1):
        observations = [_observation(p) for p in history[plant.key] if p.captured_at <= as_of]
        state = plant_state(observations, labels[plant.key])
        contexts.append(greenhouse_plans.UnitContext(unit=_SimUnit(idx, plant.key, plant.row, plant.pos), state=state,
                                                     latest_point=None, latest_under_ok_point=None))
    return patrol_planner.build_plan(
        greenhouse_plans.planner_inputs(contexts, as_of), summary, plan_date=plan_date,
        seed=patrol_planner.plan_seed(truth.seed, plan_date), params=params,
    )


class _Season:
    """一种策略跑一季：照片和人工结论都按时间累积，计划只看计划日 08:00 之前的。"""

    def __init__(self, truth: Truth, strategy: str, params: ReplayParams) -> None:
        self.truth, self.strategy, self.params = truth, strategy, params
        self.cap = params.cap_for(len(truth.plants))
        self.run = StrategyRun(strategy, self.cap, params.human_budget)
        self.history: dict[str, list[Photo]] = {p.key: [] for p in truth.plants}
        self.labels: dict[str, list[HumanLabel]] = {p.key: [] for p in truth.plants}
        self.by_key = {p.key: p for p in truth.plants}
        self.planner_params = patrol_planner.DEFAULT_PARAMS.with_overrides({"human_budget": params.human_budget})

    def plan(self, day: int) -> dict[str, Any]:
        self.run.planner_calls += 1
        return plan_for_day(self.truth, day, self.history, self.labels, self.planner_params)

    def confirm(self, day: int, plants: Sequence[TruthPlant]) -> None:
        for plant in plants[:self.params.human_budget]:
            confirmation = human_confirm(self.truth, plant, day, self.history[plant.key])
            self.labels[plant.key].append(HumanLabel(confirmation.label, self.truth.at(day, CONFIRM_TIME), "sim-human"))
            self.run.confirmations.append(confirmation)
        self.run.daily_confirms.append(min(len(plants), self.params.human_budget))

    def fixed_day(self, day: int) -> None:
        plan = self.plan(day) if self.strategy == "fixed_ranked" else None
        period = "morning" if self.strategy == "fixed_morning" else "day"
        k = self.params.fixed_every_days
        camera = _Camera(self.truth, day, period, self.cap, max_attempts=1)
        shot: list[TruthPlant] = []
        for plant in [p for i, p in enumerate(self.truth.plants) if i % k == day % k]:
            photos = camera.shoot(plant, "upper", reshoot=False) + camera.shoot(plant, "under", reshoot=False)
            if photos:
                shot.append(plant)
                self.history[plant.key].extend(photos)
        if plan is not None:
            picked = [self.by_key[item.key] for item in plan["lists"]["confirm"]]
        else:
            rng = random.Random(f"gh-replay:{self.truth.seed}:fixed-human:{day}")  # 两个随机变体抽到同一批株
            picked = sorted(rng.sample(shot, min(self.params.human_budget, len(shot))), key=lambda p: p.key)
        self.run.daily_photos.append(len(camera.photos))
        self.run.periods.append(period)
        self.confirm(day, picked)

    def risk_day(self, day: int) -> None:
        plan = self.plan(day)
        period = "morning" if plan["window"] else "day"
        camera = _Camera(self.truth, day, period, self.cap, max_attempts=int(self.truth.visibility.get("max_attempts", 3)))
        lists = plan["lists"]
        for item in lists["reshoot"]:  # 补拍只拍叶背（planner 的三角度序列简化为同一视角最多拍三次）
            self.history[item.key].extend(camera.shoot(self.by_key[item.key], "under", reshoot=True))
        for item in lists["coverage"] + lists["random"]:
            plant = self.by_key[item.key]
            self.history[item.key].extend(camera.shoot(plant, "upper", reshoot=False)
                                          + camera.shoot(plant, "under", reshoot=True))
        self.run.daily_photos.append(len(camera.photos))
        self.run.periods.append(period)
        self.confirm(day, [self.by_key[item.key] for item in lists["confirm"]])


def run_strategy(truth: Truth, strategy: str, params: ReplayParams = ReplayParams()) -> StrategyRun:
    season = _Season(truth, strategy, params)
    for day in range(truth.days):
        season.risk_day(day) if strategy == "risk" else season.fixed_day(day)
    return season.run


# ---------------------------------------------------------------- 指标与汇总


def season_metrics(truth: Truth, confirmations: Sequence[Confirmation], daily_photos: Sequence[int]) -> dict[str, Any]:
    """病株 = 季内进入早期（每天 state_hour 点）的株；提前量 = 进入明显期那天 − 首次被确认为病的那天（天，正数为提前）。"""
    first_positive: dict[str, int] = {}
    for c in confirmations:
        if c.label in POSITIVE_LABELS and c.key not in first_positive:
            first_positive[c.key] = c.day
    diseased, leads = [], []
    for plant in truth.plants:
        onset = truth.first_day(plant, ("early", "symptomatic"))
        if onset is None or onset >= truth.days:
            continue
        diseased.append(plant.key)
        symptomatic = truth.first_day(plant, ("symptomatic",))
        if plant.key in first_positive and symptomatic is not None:
            leads.append(symptomatic - first_positive[plant.key])
    confirmed = [k for k in diseased if k in first_positive]
    return {
        "diseased": len(diseased),
        "confirmed": len(confirmed),
        "missed": len(diseased) - len(confirmed),
        "confirmed_before_symptomatic": sum(1 for x in leads if x > 0),
        "lead_days_mean": round(sum(leads) / len(leads), 4) if leads else None,
        "lead_days": sorted(leads),
        "photos": sum(daily_photos),
        "confirmations": len(confirmations),
        "invalid_confirmations": sum(1 for c in confirmations if c.label == "normal"),
        "false_positive_confirmations": sum(1 for c in confirmations
                                            if c.label in POSITIVE_LABELS and c.truth_state in ("healthy", "latent")),
    }


SUMMARY_METRICS = ("diseased", "confirmed", "missed", "confirmed_before_symptomatic", "lead_days_mean", "photos",
                   "confirmations", "invalid_confirmations", "false_positive_confirmations")


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low, high = math.floor(pos), math.ceil(pos)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def aggregate(values: Sequence[float | None]) -> dict[str, Any]:
    """均值与 P10–P90（线性插值）；None 不计入，n 是参与的种子数。"""
    present = [float(v) for v in values if v is not None]
    if not present:
        return {"mean": None, "p10": None, "p90": None, "n": 0}
    return {"mean": round(sum(present) / len(present), 4), "p10": round(_quantile(present, 0.1), 4),
            "p90": round(_quantile(present, 0.9), 4), "n": len(present)}


def run_replay(truths: Sequence[dict[str, Any]], params: ReplayParams = ReplayParams()) -> dict[str, Any]:
    seeds = []
    for data in truths:
        truth = load_truth(data)
        entry: dict[str, Any] = {"seed": truth.seed, "facility_type": truth.facility_type, "plants": len(truth.plants),
                                 "days": truth.days, "strategies": {}}
        for strategy in params.strategies:
            run = run_strategy(truth, strategy, params)
            entry["strategies"][strategy] = {
                "budget": {"photo_cap": run.photo_cap, "human_budget": run.human_budget},
                "metrics": season_metrics(truth, run.confirmations, run.daily_photos),
                "daily_photos": run.daily_photos, "daily_confirms": run.daily_confirms,
                "morning_days": sum(1 for p in run.periods if p == "morning"),
                "planner_calls": run.planner_calls,
            }
        seeds.append(entry)
    seeds.sort(key=lambda e: (e["seed"], e["facility_type"]))
    summary = {
        strategy: {m: aggregate([s["strategies"][strategy]["metrics"][m] for s in seeds]) for m in SUMMARY_METRICS}
        for strategy in params.strategies
    }
    return {"report_version": REPORT_VERSION, "note": DISCLAIMER, "params": asdict(params),
            "planner": {"plan_version": patrol_planner.PLAN_VERSION, "human_budget": params.human_budget},
            "seeds": seeds, "summary": summary}


# ---------------------------------------------------------------- Markdown


METRIC_TITLES = {
    "diseased": "季内发病株（进入早期）",
    "confirmed": "确认出的病株",
    "missed": "漏掉的病株",
    "confirmed_before_symptomatic": "其中进入明显期前就确认",
    "lead_days_mean": "提前量均值（天，正数为早于明显期）",
    "photos": "照片（张/季）",
    "confirmations": "人工确认（次/季）",
    "invalid_confirmations": "其中确认为健康（无效确认）",
    "false_positive_confirmations": "其中把健康株确认为病（人工误判）",
}


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}"


def _cell(agg: dict[str, Any]) -> str:
    if agg["mean"] is None:
        return "—"
    return f"{_fmt(agg['mean'])} [{_fmt(agg['p10'])}, {_fmt(agg['p90'])}]"


def render_markdown(report: dict[str, Any]) -> str:
    params = report["params"]
    strategies = params["strategies"]
    seeds = report["seeds"]
    first = seeds[0] if seeds else {"plants": 0, "days": 0, "facility_type": "—", "strategies": {}}
    budget = next(iter(first["strategies"].values()), {}).get("budget", {})
    lines = [
        f"# 大棚巡检策略离线比较（{report['report_version']}）",
        "",
        f"> **{report['note']}**",
        "",
        f"- 真值：{len(seeds)} 个种子（{', '.join(str(s['seed']) for s in seeds)}），"
        f"{first['facility_type']}，{first['plants']} 株，季长 {first['days']} 天",
        f"- 预算（各策略相同）：每天照片上限 {budget.get('photo_cap', '—')} 张，人工确认上限 {params['human_budget']} 株",
        f"- 固定巡检：每 {params['fixed_every_days']} 天全覆盖一次（每天拍 1/{params['fixed_every_days']} 的株，"
        "正面、叶背各一张，白天拍，不补拍），人工从当天拍过的株里随机抽；"
        "「清晨拍」只把拍摄挪到清晨，「按模型分确认」照片不变、人工改看 planner 的确认名单",
        f"- 风险驱动：每天调用 {report['planner']['plan_version']}，有清晨窗口就清晨拍，叶背不合格重拍，人工确认计划的确认名单",
        "- 单元格：多种子均值 [P10, P90]",
        "",
        "| 指标 | " + " | ".join(STRATEGY_TITLES[s] for s in strategies) + " |",
        "|---|" + "---|" * len(strategies),
    ]
    for metric in SUMMARY_METRICS:
        lines.append(f"| {METRIC_TITLES[metric]} | "
                     + " | ".join(_cell(report["summary"][s][metric]) for s in strategies) + " |")
    lines += ["", "## 逐种子", "",
              "| 种子 | 病株 | " + " | ".join(f"{STRATEGY_TITLES[s]} 确认/漏/提前量" for s in strategies) + " |",
              "|---|---|" + "---|" * len(strategies)]
    for s in seeds:
        cells = []
        for strategy in strategies:
            m = s["strategies"][strategy]["metrics"]
            cells.append(f"{m['confirmed']}/{m['missed']}/{_fmt(m['lead_days_mean'])}")
        diseased = next(iter(s["strategies"].values()))["metrics"]["diseased"]
        lines.append(f"| {s['seed']} | {diseased} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
