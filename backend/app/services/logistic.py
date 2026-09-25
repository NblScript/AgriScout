"""L2 正则逻辑回归（纯 Python，不依赖 numpy）：离线重放与线上风险模型（risk-lr-*）共用。

牛顿法加 Armijo 回溯线搜索：特征共线时纯牛顿步会冲过头并发散（计划 0008 的更正），
回溯保证正则化目标单调下降；L2 使目标严格凸，收敛到唯一最优。
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """高斯消元（部分主元）。矩阵小（≤10 维），纯 Python 足够。"""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        if abs(m[col][col]) < 1e-12:
            continue
        for r in range(col + 1, n):
            factor = m[r][col] / m[col][col]
            if factor:
                for c in range(col, n + 1):
                    m[r][c] -= factor * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        if abs(m[r][r]) < 1e-12:
            continue
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


@dataclass(frozen=True, slots=True)
class LogisticModel:
    names: tuple[str, ...]
    mean: tuple[float, ...]
    std: tuple[float, ...]
    weights: tuple[float, ...]  # weights[0] 为截距

    def predict(self, features: dict[str, float]) -> float:
        z = self.weights[0] + sum(
            w * (features[n] - mu) / sd
            for w, n, mu, sd in zip(self.weights[1:], self.names, self.mean, self.std)
        )
        return _sigmoid(z)


def fit_logistic(
    rows: Sequence[dict[str, float]],
    labels: Sequence[int],
    names: Sequence[str],
    *,
    l2: float = 1.0,
    max_iter: int = 30,
) -> LogisticModel:
    """L2 正则逻辑回归（牛顿法 + 回溯线搜索），特征先按训练集标准化。

    纯牛顿步在特征共线（当前值 / 历史最大 / 变化量）时 Hessian 接近奇异，会冲过头并发散
    （曾在模拟季数据上把截距推到 -5.8 亿）。每一步都做 Armijo 回溯，保证正则化目标单调下降；
    L2 使目标严格凸，因此收敛到唯一最优。
    训练集全阴或全阳时退化为常数模型（拉普拉斯平滑的患病率），不硬拟合。
    """
    names = tuple(names)
    n = len(rows)
    positives = sum(labels)
    prior = (positives + 0.5) / (n + 1.0) if n else 0.5
    mean = tuple(sum(r[f] for r in rows) / n if n else 0.0 for f in names)
    std = tuple(
        (math.sqrt(sum((r[f] - mu) ** 2 for r in rows) / n) or 1.0) if n else 1.0
        for f, mu in zip(names, mean)
    )
    bias = math.log(prior / (1 - prior))
    if n == 0 or positives in (0, n):
        return LogisticModel(names, mean, std, (bias,) + (0.0,) * len(names))
    xs = [[1.0] + [(r[f] - mu) / sd for f, mu, sd in zip(names, mean, std)] for r in rows]
    d = len(names) + 1

    def objective(w: list[float]) -> float:
        """负对数似然 + L2（截距不罚）；softplus 用稳定写法。"""
        total = 0.5 * l2 * sum(wj * wj for wj in w[1:])
        for x, y in zip(xs, labels):
            z = sum(wj * xj for wj, xj in zip(w, x))
            total += (z + math.log1p(math.exp(-z)) if z > 0 else math.log1p(math.exp(z))) - y * z
        return total

    w = [bias] + [0.0] * (d - 1)
    current = objective(w)
    for _ in range(max_iter):
        grad = [l2 * w[j] if j else 0.0 for j in range(d)]
        hess = [[(l2 if i == j and i else (1e-6 if i == j else 0.0)) for j in range(d)] for i in range(d)]
        for x, y in zip(xs, labels):
            p = _sigmoid(sum(wj * xj for wj, xj in zip(w, x)))
            r = p - y
            s = p * (1 - p)
            for i in range(d):
                grad[i] += r * x[i]
                si = s * x[i]
                row = hess[i]
                for j in range(i, d):
                    row[j] += si * x[j]
        for i in range(d):
            for j in range(i):
                hess[i][j] = hess[j][i]
        step = _solve(hess, grad)
        slope = sum(g * st for g, st in zip(grad, step))  # 下降方向时为正
        t = 1.0
        while True:
            candidate = [wi - t * si for wi, si in zip(w, step)]
            value = objective(candidate)
            if value <= current - 1e-4 * t * slope or t < 1e-10:
                break
            t *= 0.5
        if value > current:  # 连回溯都无法下降：已在数值精度内收敛
            break
        w, current = candidate, value
        if max(abs(t * si) for si in step) < 1e-7:
            break
    return LogisticModel(names, mean, std, tuple(w))


def model_to_dict(model: LogisticModel) -> dict[str, Any]:
    return {"features": list(model.names), "mean": list(model.mean), "std": list(model.std),
            "weights": list(model.weights)}


def model_from_dict(data: dict[str, Any]) -> LogisticModel:
    names = tuple(data["features"])
    mean, std, weights = tuple(data["mean"]), tuple(data["std"]), tuple(data["weights"])
    if not (len(names) == len(mean) == len(std) == len(weights) - 1):
        raise ValueError("模型参数维度不一致：features/mean/std/weights")
    if any(sd <= 0 for sd in std):
        raise ValueError("模型标准差必须为正")
    if not all(math.isfinite(v) for v in (*mean, *std, *weights)):
        raise ValueError("模型参数含非有限值")
    return LogisticModel(names, mean, std, weights)
