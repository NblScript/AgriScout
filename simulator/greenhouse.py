"""大棚黄瓜霜霉病模拟世界（计划 0017，纯模型，不做任何 IO）。

给 ``greenhouse_run.py``（只走 HTTP 的闭环）和后端离线策略比较提供同一份「真值世界」：
1. **布局**：日光温室或塑料大棚，若干垄 × 若干株，株号 ``R{垄两位}-P{株三位}``（计划 0013 共同约定）。
2. **小时环境**：温湿度按日变化（余弦 + 逐日漂移 + 噪声，种子控制）；塑料大棚昼夜温差更大、夜间更湿。
   露点和湿润判据按计划 0015 的公式在这里独立实现一份（红线 6：不 import 后端）。
3. **病害**：每株 healthy → latent → early → symptomatic。每个「湿润且温度适宜」的小时，
   感染概率 = 外源基数 + β × 处于明显期的邻株数（8 邻域）；潜伏期和早期持续天数在区间内随机。
4. **可见性**：按 视角（叶背 / 正面）× 时段（清晨 / 白天）× 状态 给出拍到病斑的概率，另有各视角拍摄不合格概率和补拍成功概率。

**所有参数都是设计假设，不是实测**（资料对早期病斑先出现在叶背还是正面说法不一）；
病害规律是按设计放进来的，所以用它跑出的结论只能证明流程跑通，不能当作效果证据（D5 红旗）。
只用标准库；可在仓库根目录 ``from simulator import greenhouse`` 测试。
"""
from __future__ import annotations

import copy
import math
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

FACILITIES = ("solar_greenhouse", "plastic_tunnel")
STATES = ("healthy", "latent", "early", "symptomatic")
STATE_CODES = {"healthy": "H", "latent": "L", "early": "E", "symptomatic": "S"}
SIDES = ("under", "upper")
PERIODS = ("morning", "day")
# 每天按当地这个钟点取「当天状态」（计划日 08:00 截止，与平台计划口径一致）
STATE_HOUR = 8

TZ_CN = timezone(timedelta(hours=8))
TRUTH_SCHEMA = "agriscout.greenhouse-truth.v1"
DISCLAIMER = "模拟结论只证明流程：病害规律与可见性参数都是设计假设（D5），不能当作效果证据"

# Magnus 公式系数（与计划 0015 相同的常用取值，独立实现）
MAGNUS_A = 17.62
MAGNUS_B = 243.12


# ---------------------------------------------------------------- 布局


@dataclass(frozen=True)
class Layout:
    facility_type: str = "solar_greenhouse"
    rows: int = 4
    plants_per_row: int = 30
    spacing_m: float = 0.4  # 株距
    row_spacing_m: float = 1.2  # 垄距

    def __post_init__(self) -> None:
        if self.facility_type not in FACILITIES:
            raise ValueError(f"设施类型只能是 {FACILITIES}")
        if not (1 <= self.rows <= 99 and 1 <= self.plants_per_row <= 999):
            raise ValueError("株号格式 R{两位}-P{三位}：垄数 1–99，每垄 1–999 株")

    @staticmethod
    def key(row: int, pos: int) -> str:
        return f"R{row:02d}-P{pos:03d}"

    def plants(self) -> list[tuple[str, int, int]]:
        """(株号, 垄号, 株序号)，按株号排序。"""
        return [(self.key(r, p), r, p) for r in range(1, self.rows + 1) for p in range(1, self.plants_per_row + 1)]

    def neighbors(self, row: int, pos: int) -> list[str]:
        """8 邻域：同垄前后一株加相邻两垄的对应三株。"""
        out = []
        for dr in (-1, 0, 1):
            for dp in (-1, 0, 1):
                r, p = row + dr, pos + dp
                if (dr, dp) != (0, 0) and 1 <= r <= self.rows and 1 <= p <= self.plants_per_row:
                    out.append(self.key(r, p))
        return out


# ---------------------------------------------------------------- 小时环境


@dataclass(frozen=True)
class ClimateParams:
    """棚内温湿度的日变化（设计假设）：温度最高、湿度最低出现在 warmest_hour 点。"""

    temp_mean_c: float
    temp_amp_c: float  # 半日较差：日温差约为它的两倍
    rh_mean: float
    rh_amp: float
    temp_noise_c: float = 0.6
    rh_noise: float = 2.0
    day_temp_sigma: float = 1.2  # 逐日漂移（一阶自回归），模拟阴晴交替
    day_rh_sigma: float = 3.0
    day_persistence: float = 0.6
    warmest_hour: int = 14


# 日光温室保温好、昼夜温差小；塑料大棚夜间散热快、降温结露更重（0013 场景约束），数值是设计假设
CLIMATES: dict[str, ClimateParams] = {
    "solar_greenhouse": ClimateParams(temp_mean_c=20.0, temp_amp_c=5.0, rh_mean=84.0, rh_amp=11.0),
    "plastic_tunnel": ClimateParams(temp_mean_c=18.0, temp_amp_c=8.0, rh_mean=86.0, rh_amp=14.0),
}


@dataclass(frozen=True)
class WetParams:
    """湿润判据，与计划 0015 dm-env-v0 同口径：相对湿度 ≥95% 或露点差 ≤1℃。"""

    wet_rh_min: float = 95.0
    wet_dewpoint_depression_max: float = 1.0


def dew_point(temp_c: float, humidity_pct: float) -> float | None:
    if humidity_pct <= 0:
        return None
    gamma = math.log(min(humidity_pct, 100.0) / 100.0) + MAGNUS_A * temp_c / (MAGNUS_B + temp_c)
    return MAGNUS_B * gamma / (MAGNUS_A - gamma)


def is_wet(temp_c: float, humidity_pct: float, params: WetParams = WetParams()) -> bool:
    td = dew_point(temp_c, humidity_pct)
    return humidity_pct >= params.wet_rh_min or (td is not None and temp_c - td <= params.wet_dewpoint_depression_max)


@dataclass(frozen=True)
class HourEnv:
    day: int  # 相对第 0 天；季前预热的天数为负
    hour: int  # 当地钟点 0–23
    temp_c: float
    humidity_pct: float
    wet: bool


def generate_climate(climate: ClimateParams, days: int, rng: random.Random, *, pre_days: int = 0,
                     wet: WetParams = WetParams()) -> list[HourEnv]:
    """第 -pre_days 天 0 点到第 days-1 天 23 点的逐小时温湿度。"""
    out: list[HourEnv] = []
    t_off = rh_off = 0.0
    for day in range(-pre_days, days):
        t_off = climate.day_persistence * t_off + rng.gauss(0, climate.day_temp_sigma)
        rh_off = climate.day_persistence * rh_off + rng.gauss(0, climate.day_rh_sigma)
        for hour in range(24):
            phase = math.cos(2 * math.pi * (hour - climate.warmest_hour) / 24)
            temp = climate.temp_mean_c + t_off + climate.temp_amp_c * phase + rng.gauss(0, climate.temp_noise_c)
            rh = climate.rh_mean + rh_off - climate.rh_amp * phase + rng.gauss(0, climate.rh_noise)
            rh = max(30.0, min(100.0, rh))
            temp, rh = round(temp, 2), round(rh, 1)
            out.append(HourEnv(day, hour, temp, rh, is_wet(temp, rh, wet)))
    return out


# ---------------------------------------------------------------- 病害


@dataclass(frozen=True)
class DiseaseParams:
    """侵染与发展（设计假设，非实测）。"""

    base_rate: float = 0.0012  # 外源孢子囊造成的侵染概率（每个湿润且温度适宜的小时）
    beta: float = 0.004  # 每个明显期邻株增加的侵染概率（同上，每小时）
    # 侵染需要的温度区间；比平台环境指标的「适宜」(15–25℃) 放宽，免得模拟器与计划器的判据完全重合
    infect_temp_min: float = 12.0
    infect_temp_max: float = 26.0
    latent_days: tuple[int, int] = (4, 6)  # 侵染到出现早期征兆（含两端）
    early_days: tuple[int, int] = (3, 5)  # 早期持续多久转为明显


@dataclass(frozen=True)
class PlantTruth:
    key: str
    row: int
    pos: int
    infected_hour: int | None = None  # 绝对小时 = 天 × 24 + 钟点
    early_hour: int | None = None
    symptomatic_hour: int | None = None

    def state_at(self, abs_hour: int) -> str:
        if self.infected_hour is None or abs_hour < self.infected_hour:
            return "healthy"
        if abs_hour < self.early_hour:
            return "latent"
        if abs_hour < self.symptomatic_hour:
            return "early"
        return "symptomatic"


def infection_probability(env: HourEnv, symptomatic_neighbors: int, params: DiseaseParams) -> float:
    """环境项（湿润 × 温度适宜，0 或 1）×（外源基数 + β × 明显邻株数）。"""
    if not env.wet or not (params.infect_temp_min <= env.temp_c <= params.infect_temp_max):
        return 0.0
    return min(1.0, params.base_rate + params.beta * symptomatic_neighbors)


def run_disease(layout: Layout, env: Sequence[HourEnv], params: DiseaseParams, rng: random.Random, *,
                initial_symptomatic: Sequence[str] = ()) -> dict[str, PlantTruth]:
    """逐小时推进；env 只用第 0 天起的小时。initial_symptomatic 的株在第 0 天 0 点已处于明显期（测试与发病中心用）。"""
    plants = layout.plants()
    infected: dict[str, int] = {}
    early: dict[str, int] = {}
    symptomatic: dict[str, int] = {}
    for key in initial_symptomatic:
        infected[key] = early[key] = symptomatic[key] = 0
    neighbors = {key: layout.neighbors(r, p) for key, r, p in plants}
    for hour_env in env:
        if hour_env.day < 0:
            continue
        now = hour_env.day * 24 + hour_env.hour
        newly = []
        for key, _r, _p in plants:
            if key in infected:
                continue
            n_sym = sum(1 for n in neighbors[key] if symptomatic.get(n, math.inf) <= now)
            if rng.random() < infection_probability(hour_env, n_sym, params):
                newly.append(key)
        for key in newly:  # 本小时新侵染的株要到潜伏期后才产孢，不影响同一小时的其他株
            infected[key] = now
            early[key] = now + 24 * rng.randint(*params.latent_days)
            symptomatic[key] = early[key] + 24 * rng.randint(*params.early_days)
    return {key: PlantTruth(key, r, p, infected.get(key), early.get(key), symptomatic.get(key))
            for key, r, p in plants}


# ---------------------------------------------------------------- 可见性与拍摄质量


def _default_detect() -> dict[str, dict[str, dict[str, float]]]:
    # 检出 = 这张照片上能看出病斑。健康和潜伏期的数值是误检（叶片老化斑、药渍等）。
    # 早期以叶背清晨最明显、正面几乎看不到；明显期两面都容易看到。全部是设计假设，试拍后用实测替换。
    background = {"under": {"morning": 0.03, "day": 0.03}, "upper": {"morning": 0.02, "day": 0.02}}
    return {
        "healthy": copy.deepcopy(background),
        "latent": copy.deepcopy(background),
        "early": {"under": {"morning": 0.70, "day": 0.35}, "upper": {"morning": 0.10, "day": 0.10}},
        "symptomatic": {"under": {"morning": 0.95, "day": 0.95}, "upper": {"morning": 0.80, "day": 0.80}},
    }


@dataclass
class VisibilityParams:
    detect: dict[str, dict[str, dict[str, float]]] = field(default_factory=_default_detect)
    # 第一次拍不合格的概率：叶背仰拍更容易虚焦、逆光
    reject: dict[str, float] = field(default_factory=lambda: {"under": 0.25, "upper": 0.08})
    reshoot_success: float = 0.7  # 补拍（第 2 次起）合格的概率
    max_attempts: int = 3

    def detect_prob(self, state: str, side: str, period: str) -> float:
        return self.detect[state][side][period]

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PhotoSample:
    side: str
    period: str
    attempt: int
    accepted: bool
    detected: bool  # 不合格的照片一律看不出病斑


def sample_photo(rng: random.Random, state: str, side: str, period: str, attempt: int,
                 params: VisibilityParams) -> PhotoSample:
    ok_prob = 1.0 - params.reject[side] if attempt == 1 else params.reshoot_success
    accepted = rng.random() < ok_prob
    detected = accepted and rng.random() < params.detect_prob(state, side, period)
    return PhotoSample(side, period, attempt, accepted, detected)


def shoot_view(rng: random.Random, state: str, side: str, period: str, params: VisibilityParams, *,
               reshoot: bool) -> list[PhotoSample]:
    """拍一个视角：reshoot=True 时不合格就补拍，最多 max_attempts 次；否则只拍一次。"""
    photos = []
    for attempt in range(1, (params.max_attempts if reshoot else 1) + 1):
        photo = sample_photo(rng, state, side, period, attempt, params)
        photos.append(photo)
        if photo.accepted:
            break
    return photos


# ---------------------------------------------------------------- 照片分数与人工确认


# 合格叶背图在分析器里的风险分（闭环里由占位分析器在合成叶片图上算出，greenhouse_run 按这几档标定病斑面积；
# 离线比较直接用这几档）：看得出病斑时明显期 0.85、早期 0.55，健康株误检 0.5，看不出病斑 0.1。
PHOTO_SCORES = {"symptomatic": 0.85, "early": 0.55, "false_positive": 0.5, "none": 0.1}
# 人工确认的三个标签（计划 0015 每株状态口径）；潜伏期肉眼看不出，按健康记
CONFIRM_LABELS = ("normal", "downy_mildew_early", "downy_mildew_symptomatic")
TRUE_LABEL = {"healthy": "normal", "latent": "normal", "early": "downy_mildew_early",
              "symptomatic": "downy_mildew_symptomatic"}
HUMAN_ERROR = 0.05  # 人工误判率（设计假设）


def photo_score_band(photo: PhotoSample, state: str) -> str:
    """照片对应的分数档：只有看得出病斑才按状态给高分。"""
    if not photo.detected:
        return "none"
    return state if state in ("early", "symptomatic") else "false_positive"


def human_label(rng: random.Random, seen: Sequence[tuple[str, bool]], error: float = HUMAN_ERROR) -> str:
    """人看这株最近的合格照片下结论。

    seen：按拍摄先后排列的 (拍摄时的真值状态, 照片上是否看得出病斑)。最近一张看得出病斑的照片决定结论
    （健康株上的误检人能认出来，记 normal）；都看不出就记 normal。再以 error 的概率误判成另外两个标签之一。
    """
    label = "normal"
    for state, detected in reversed(seen):
        if detected:
            label = TRUE_LABEL[state]
            break
    if rng.random() < error:
        label = rng.choice([x for x in CONFIRM_LABELS if x != label])
    return label


# ---------------------------------------------------------------- 世界


@dataclass
class World:
    layout: Layout
    seed: int
    days: int  # 模拟季天数（巡检在这些天里发生）
    extra_days: int  # 季后再推几天，只用于查「何时转为明显」
    pre_days: int  # 季前环境预热天数（让第 0 天就有 72 小时环境指数）
    climate: ClimateParams
    disease: DiseaseParams
    visibility: VisibilityParams
    env: list[HourEnv]
    plants: dict[str, PlantTruth]

    def state(self, key: str, day: int, hour: int = STATE_HOUR) -> str:
        return self.plants[key].state_at(day * 24 + hour)

    def daily_codes(self, key: str) -> str:
        """第 0 天到季后最后一天，每天 STATE_HOUR 点的状态码（H/L/E/S）。"""
        return "".join(STATE_CODES[self.state(key, d)] for d in range(self.days + self.extra_days))

    def summary(self) -> dict:
        total = self.days + self.extra_days
        end = self.days * 24
        season = [h for h in self.env if 0 <= h.day < self.days]
        return {
            "plants": len(self.plants),
            "infected_in_season": sum(1 for p in self.plants.values() if p.infected_hour is not None and p.infected_hour < end),
            "early_in_season": sum(1 for p in self.plants.values() if p.early_hour is not None and p.early_hour < end),
            "symptomatic_by_end": sum(1 for p in self.plants.values()
                                      if p.symptomatic_hour is not None and p.symptomatic_hour < total * 24),
            "wet_hours_per_day": round(sum(h.wet for h in season) / max(self.days, 1), 2),
        }


def to_truth(world: World, day0: date, *, human_error: float = HUMAN_ERROR,
             closed_loop: dict | None = None) -> dict:
    """真值 JSON（模拟器与后端离线比较之间的合同，``agriscout.greenhouse-truth.v1``）。

    小时都是相对 day0 当地 0 点的绝对小时；daily_states 是每天 STATE_HOUR 点的状态码，覆盖季内加季后。
    """
    start = datetime.combine(day0, datetime.min.time(), tzinfo=TZ_CN)
    return {
        "schema": TRUTH_SCHEMA,
        "note": DISCLAIMER,
        "seed": world.seed,
        "facility_type": world.layout.facility_type,
        "layout": asdict(world.layout),
        "day0": day0.isoformat(),
        "days": world.days,
        "extra_days": world.extra_days,
        "pre_days": world.pre_days,
        "state_hour": STATE_HOUR,
        "env_hourly": [
            {"at": (start + timedelta(hours=h.day * 24 + h.hour)).isoformat(), "temp_c": h.temp_c,
             "humidity_pct": h.humidity_pct, "wet": h.wet}
            for h in world.env
        ],
        "plants": [asdict(p) for p in sorted(world.plants.values(), key=lambda p: p.key)],
        "daily_states": {key: world.daily_codes(key) for key in sorted(world.plants)},
        "visibility": world.visibility.as_dict(),
        "photo_scores": dict(PHOTO_SCORES),
        "human_error": human_error,
        "params": {"climate": asdict(world.climate), "disease": asdict(world.disease), "wet": asdict(WetParams())},
        "summary": world.summary(),
        "closed_loop": closed_loop,
    }


def simulate(layout: Layout, *, seed: int, days: int = 30, extra_days: int = 10, pre_days: int = 4,
             climate: ClimateParams | None = None, disease: DiseaseParams | None = None,
             visibility: VisibilityParams | None = None, initial_symptomatic: Sequence[str] = ()) -> World:
    climate = climate or CLIMATES[layout.facility_type]
    disease = disease or DiseaseParams()
    rng = random.Random(f"greenhouse:{seed}")
    env = generate_climate(climate, days + extra_days, rng, pre_days=pre_days)
    plants = run_disease(layout, env, disease, rng, initial_symptomatic=initial_symptomatic)
    return World(layout, seed, days, extra_days, pre_days, climate, disease, visibility or VisibilityParams(), env, plants)


def diurnal_range(env: Sequence[HourEnv]) -> float:
    """季内（第 0 天起）平均日温差。"""
    by_day: dict[int, list[float]] = {}
    for h in env:
        if h.day >= 0:
            by_day.setdefault(h.day, []).append(h.temp_c)
    return sum(max(v) - min(v) for v in by_day.values()) / max(len(by_day), 1)
