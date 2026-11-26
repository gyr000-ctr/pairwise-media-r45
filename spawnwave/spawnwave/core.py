"""spawnwave 核心 API（仅标准库）。

波次预算分配（整数规划）：

- ``budget(n)``：第 ``n`` 波预算，即难度曲线值。曲线可以是一维
  ``curve(n)`` 或二维 ``curve(n, level)``（波次、玩家等级），
  返回值与解析式完全一致（不做任何修正，误差 0 ≤ 1e-9），
  单调性由曲线本身保证。
- ``wave(n)``：在 ``数量 × 单位成本 ≤ 预算`` 约束下的整数分配。
  总花费通过剩余类最短路（unbounded knapsack 精确解）达到最优，
  因此种类 ≤ 6 时与暴力最优解的总价值差 ≤ 0（实际为 0）；
  在并列最优解之间按 ``(seed, n, level)`` 确定性随机选择，
  同种子可复现，不同种子一般不同。
- 非法输入抛出 ``ValueError`` 的可区分子类：
  空/非法成本表 → ``CostsError``；非法波次 → ``WaveNumberError``；
  预算为负 → ``NegativeBudgetError``；预算为 NaN/无穷 →
  ``NonFiniteBudgetError``；曲线不可调用 → ``CurveError``。
"""

from __future__ import annotations

import heapq
import inspect
import math
import random
from math import gcd

__all__ = [
    "SpawnWave",
    "SpawnWaveError",
    "CurveError",
    "CostsError",
    "WaveNumberError",
    "LevelError",
    "BudgetError",
    "NegativeBudgetError",
    "NonFiniteBudgetError",
]


class SpawnWaveError(ValueError):
    """spawnwave 所有非法输入错误的可区分基类。"""


class CurveError(SpawnWaveError):
    """难度曲线不可调用。"""


class CostsError(SpawnWaveError):
    """单位成本表为空或含非法成本。"""


class WaveNumberError(SpawnWaveError):
    """波次编号非法（非整数或 < 1）。"""


class LevelError(SpawnWaveError):
    """玩家等级非法。"""


class BudgetError(SpawnWaveError):
    """预算非法的基类（曲线返回值不是有效预算）。"""


class NegativeBudgetError(BudgetError):
    """预算为负数。"""


class NonFiniteBudgetError(BudgetError):
    """预算为 NaN 或无穷。"""


# 最小单位成本（约化后）超过该值时不再建剩余类图，退化为贪心。
_RESIDUE_CAP = 100_000
# 整数路径处理的预算上限（避免巨浮点转整数的精度问题）。
_INT_BUDGET_CAP = 1e15


def _curve_is_2d(fn):
    """判断曲线是否必须接受 (n, level) 两个位置参数。

    只有第二个位置参数无默认值时才按二维调用 ``curve(n, level)``；
    带默认值的曲线用单参数 ``curve(n)`` 调用即可正常工作。
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    required = 0
    for p in sig.parameters.values():
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            if p.default is p.empty:
                required += 1
    return required >= 2


def _check_wave_number(n):
    if isinstance(n, bool) or not isinstance(n, int):
        raise WaveNumberError("波次编号必须是整数，得到 {!r}".format(n))
    if n < 1:
        raise WaveNumberError("波次编号必须 >= 1，得到 {!r}".format(n))
    return n


def _check_level(level):
    if isinstance(level, bool) or not isinstance(level, int):
        raise LevelError("玩家等级必须是整数，得到 {!r}".format(level))
    if level < 0:
        raise LevelError("玩家等级必须 >= 0，得到 {!r}".format(level))
    return level


def _build_residue_graph(coins):
    """以最小单位成本为模建立剩余类最短路图。

    coins: [(name, 约化后整数成本)]，gcd 全部为 1。
    返回 (m, dist, prev, max_dist, min_name)：
    dist[r] 为 ≡ r (mod m) 的最小可表示花费，prev 用于回溯出一种表示。
    """
    m = min(c for _, c in coins)
    dist = [None] * m
    prev = [None] * m
    dist[0] = 0
    heap = [(0, 0)]
    while heap:
        d, r = heapq.heappop(heap)
        if dist[r] is not None and d > dist[r]:
            continue
        for name, c in coins:
            r2 = (r + c) % m
            d2 = d + c
            if dist[r2] is None or d2 < dist[r2]:
                dist[r2] = d2
                prev[r2] = (r, name)
                heapq.heappush(heap, (d2, r2))
    min_name = min(coins, key=lambda t: (t[1], str(t[0])))[0]
    max_dist = max(dist)
    return m, dist, prev, max_dist, min_name


class SpawnWave:
    """波次预算分配器。

    :param curve: 难度曲线，``curve(n)`` 或 ``curve(n, level)``，
        返回第 ``n`` 波的预算（对波次与等级单调不减）。
    :param costs: ``{种类: 单位成本}``，成本为正的有限数值，非空。
    :param seed: 随机种子，同种子同波次结果可复现。
    :param level: 默认玩家等级（二维曲线时使用，默认 1）。
    """

    def __init__(self, curve, costs, seed, level=1):
        if not callable(curve):
            raise CurveError("curve 必须可调用，得到 {!r}".format(curve))
        self._curve = curve
        self._curve2d = _curve_is_2d(curve)

        try:
            items = list(dict(costs).items())
        except (TypeError, ValueError):
            raise CostsError("costs 必须是 {种类: 单位成本} 映射") from None
        if not items:
            raise CostsError("costs 不能为空")
        norm = {}
        for name, c in items:
            if isinstance(c, bool) or not isinstance(c, (int, float)):
                raise CostsError("种类 {!r} 的单位成本不是数值: {!r}".format(name, c))
            fc = float(c)
            if math.isnan(fc) or math.isinf(fc):
                raise CostsError("种类 {!r} 的单位成本非有限值: {!r}".format(name, c))
            if fc <= 0.0:
                raise CostsError("种类 {!r} 的单位成本必须为正: {!r}".format(name, c))
            norm[name] = fc
        self._costs = norm

        self._seed = seed
        self._level = _check_level(level)

        # 整数精确路径：所有成本都是整数值且规模可承受时，
        # 预计算剩余类最短路（与预算无关，只与成本有关）。
        self._int_plan = None
        if all(c.is_integer() for c in norm.values()):
            raw = [(k, int(c)) for k, c in norm.items()]
            g = 0
            for _, c in raw:
                g = gcd(g, c)
            coins = [(k, c // g) for k, c in raw]
            m = min(c for _, c in coins)
            if m <= _RESIDUE_CAP:
                mg, dist, prev, max_dist, min_name = _build_residue_graph(coins)
                self._int_plan = (g, mg, dist, prev, max_dist, min_name)

    # ------------------------------------------------------------------ #
    # 预算
    # ------------------------------------------------------------------ #

    def _resolve_level(self, level):
        return self._level if level is None else _check_level(level)

    def _budget_value(self, n, level):
        if self._curve2d:
            raw = self._curve(n, level)
        else:
            raw = self._curve(n)
        try:
            b = float(raw)
        except (TypeError, ValueError, ArithmeticError):
            raise BudgetError(
                "第 {} 波预算不是数值: {!r}".format(n, raw)
            ) from None
        if math.isnan(b):
            raise NonFiniteBudgetError("第 {} 波预算为 NaN".format(n))
        if math.isinf(b):
            raise NonFiniteBudgetError("第 {} 波预算为无穷".format(n))
        if b < 0.0:
            raise NegativeBudgetError("第 {} 波预算为负: {!r}".format(n, b))
        return b

    def budget(self, n, level=None):
        """第 ``n`` 波的预算（float，与曲线解析式一致）。"""
        _check_wave_number(n)
        return self._budget_value(n, self._resolve_level(level))

    # ------------------------------------------------------------------ #
    # 分配
    # ------------------------------------------------------------------ #

    def _optimal_spend(self, budget_int):
        """整数预算下的最大可表示花费与对应剩余类。"""
        g, m, dist, prev, max_dist, _ = self._int_plan
        q = budget_int // g
        if q >= max_dist:
            # 超过 Frobenius 界，q 本身必可表示。
            r = q % m
            return g * q, r
        best_val = -1
        best_r = 0
        for r in range(m):
            d = dist[r]
            if d is not None and d <= q:
                val = d + m * ((q - d) // m)
                if val > best_val:
                    best_val = val
                    best_r = r
        return g * best_val, best_r

    def _witness_counts(self, r, k_min, counts=None):
        """回溯剩余类 r 的一种表示，并补上 k_min 个最小成本单位。"""
        g, m, dist, prev, max_dist, min_name = self._int_plan
        if counts is None:
            counts = {}
        while r:
            pr, name = prev[r]
            counts[name] = counts.get(name, 0) + 1
            r = pr
        if k_min:
            counts[min_name] = counts.get(min_name, 0) + k_min
        return counts

    @staticmethod
    def _key(counts):
        return tuple(sorted((k, v) for k, v in counts.items() if v > 0))

    def _candidates(self, budget_int):
        """所有"单品种贪心取最大 + 剩余精确填充"且总花费最优的方案。"""
        g, m, dist, prev, max_dist, min_name = self._int_plan
        best, r = self._optimal_spend(budget_int)
        found = set()
        # 纯最短路见证方案。
        q = budget_int // g
        witness = self._witness_counts(r, (q - dist[r]) // m)
        found.add(self._key(witness))
        # 每个品种先贪心取最大，再把余量精确填满。
        for name, fc in sorted(self._costs.items(), key=lambda t: str(t[0])):
            c = int(fc)
            x = budget_int // c
            if x <= 0:
                continue
            rem = budget_int - x * c
            rem_best, rr = self._optimal_spend(rem)
            if x * c + rem_best != best:
                continue
            counts = self._witness_counts(rr, (rem // g - dist[rr]) // m,
                                          {name: x})
            found.add(self._key(counts))
        return sorted(found)

    def _allocate_int(self, budget_int, n, level):
        cands = self._candidates(budget_int)
        rng = random.Random("{}:{}:{}".format(self._seed, n, level))
        pick = cands[rng.randrange(len(cands))]
        return dict(pick)

    def _allocate_greedy(self, budget, n, level):
        """非整数成本等情形的回退：按种子洗牌顺序贪心取最大。"""
        order = sorted(self._costs, key=str)
        rng = random.Random("greedy:{}:{}:{}".format(self._seed, n, level))
        rng.shuffle(order)
        remaining = budget
        counts = {}
        for name in order:
            c = self._costs[name]
            x = int(remaining // c)
            if x > 0:
                counts[name] = x
                remaining -= x * c
        return counts

    def wave(self, n, level=None):
        """第 ``n`` 波的分配：``{种类: 整数数量}``，数量×成本 ≤ 预算。"""
        _check_wave_number(n)
        lvl = self._resolve_level(level)
        b = self._budget_value(n, lvl)
        if self._int_plan is not None and b <= _INT_BUDGET_CAP:
            return self._allocate_int(int(math.floor(b)), n, lvl)
        return self._allocate_greedy(b, n, lvl)
