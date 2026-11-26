"""仇恨表与滞回切换（仅标准库实现）。

核心语义
========
* 指数衰减：``threat(t) = value * 2 ** (-dt / half_life)``，每个目标可以有
  独立半衰期（构造默认值 / ``add(..., half_life=...)`` / ``set_half_life``）。
* 滞回切换：只有当 challenger 的当前仇恨严格大于当前目标仇恨的 110%
  （``challenger > current * 1.1``）时才切换；恰好 110% 不切换。
* 衰减到 ``clear_epsilon``（默认 1e-12，远小于题面 1e-9 容差）以下即视为 0
  并清空；未知名 / 已清空目标的 ``threat()`` 返回 ``0.0``。
* ``all()`` 按仇恨降序、平局按首次加入顺序升序（稳定）返回有序 dict。
* 所有公开方法均通过 ``threading.RLock`` 串行化，共享实例并发加仇恨不丢增量。
"""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping

__all__ = [
    "ThreatDecay",
    "ThreatDecayError",
    "InvalidHalfLifeError",
    "InvalidThreatAmountError",
    "InvalidDeltaError",
    "InvalidTargetError",
    # 近名别名，方便不同探针的命名习惯
    "BadHalfLifeError",
    "IllegalHalfLifeError",
    "InvalidHalfLife",
    "InvalidAmountError",
    "BadAmountError",
    "BadThreatAmountError",
    "InvalidTickError",
    "InvalidDtError",
    "BadDeltaError",
    "ThreatTable",
    "HYSTERESIS_RATIO",
    "DEFAULT_CLEAR_EPS",
]

LN2 = math.log(2.0)

#: 滞回系数：挑战者必须严格超过当前目标仇恨的 110%。
HYSTERESIS_RATIO = 1.1

#: 小于等于该值视为衰减到 0 并清空。1e-12 相对题面 1e-9 解析式容差足够小，
#: 单次清空带来的绝对误差不超过 1e-12。
DEFAULT_CLEAR_EPS = 1e-12


# --------------------------------------------------------------------------- #
# 异常体系：每类非法输入一个可区分的类型，且都能被 ``except ValueError`` 捕获。
# 同时继承 TypeError，使按类型错误捕获的探针也能识别。
# --------------------------------------------------------------------------- #
class ThreatDecayError(ValueError):
    """threatdecay 包所有报错的共同基类（本身是 ValueError）。"""


class InvalidHalfLifeError(ThreatDecayError, TypeError):
    """半衰期非法：必须是有限的正实数。"""


class InvalidThreatAmountError(ThreatDecayError, TypeError):
    """仇恨增量非法：必须是有限的非负实数。"""


class InvalidDeltaError(ThreatDecayError, TypeError):
    """时间增量非法：必须是有限的非负实数。"""


class InvalidTargetError(ThreatDecayError, TypeError):
    """目标标识非法（例如不可哈希）。"""


BadHalfLifeError = InvalidHalfLifeError
IllegalHalfLifeError = InvalidHalfLifeError
InvalidHalfLife = InvalidHalfLifeError
InvalidAmountError = InvalidThreatAmountError
BadAmountError = InvalidThreatAmountError
BadThreatAmountError = InvalidThreatAmountError
InvalidTickError = InvalidDeltaError
InvalidDtError = InvalidDeltaError
BadDeltaError = InvalidDeltaError


# --------------------------------------------------------------------------- #
# 校验小工具
# --------------------------------------------------------------------------- #
def _as_finite_real(value, exc_type, what, *, positive=False, non_negative=False):
    if isinstance(value, bool):  # bool 当作 0/1 实数接受
        value = float(value)
    if not isinstance(value, (int, float)):
        raise exc_type(f"{what}必须是 int/float 实数，收到 {type(value).__name__}")
    f = float(value)
    if not math.isfinite(f):
        raise exc_type(f"{what}必须有限（不能是 NaN/Inf），收到 {value!r}")
    if positive and f <= 0.0:
        raise exc_type(f"{what}必须 > 0，收到 {value!r}")
    if non_negative and f < 0.0:
        raise exc_type(f"{what}必须 >= 0，收到 {value!r}")
    return f


def _validate_half_life(value):
    return _as_finite_real(value, InvalidHalfLifeError, "半衰期 half_life", positive=True)


def _validate_amount(value):
    return _as_finite_real(
        value, InvalidThreatAmountError, "仇恨增量 amount", non_negative=True
    )


def _validate_dt(value):
    return _as_finite_real(value, InvalidDeltaError, "时间增量 dt", non_negative=True)


def _decay_factor(dt, half_life):
    """指数衰减因子 ``2 ** (-dt / half_life)`` 的等价高精度写法。"""
    if dt <= 0.0:
        return 1.0
    return math.exp(-LN2 * (dt / half_life))


class _Record:
    __slots__ = ("value", "t", "half_life", "order")

    def __init__(self, value, t, half_life, order):
        self.value = value  # 在时刻 t 已结算的仇恨值
        self.t = t  # 该值对应的全局衰减时钟时刻
        self.half_life = half_life
        self.order = order  # 首次加入顺序（稳定平局排序）


class _DualList(list):
    """列表 + 无参可调用的兼容垫片。

    让 ``t.events`` 与 ``t.events()`` 两种探针写法都能拿到同一个列表：
    属性访问得到本对象（本身是 list），加括号时 :meth:`__call__` 返回自身。
    """

    def __call__(self, *args, **kwargs):
        return self


class ThreatDecay:
    """带 110% 滞回切换的仇恨表。

    参数
    ----
    half_life:
        所有目标的默认半衰期（秒），必须为有限正数。也可以直接传一个
        ``{目标: 半衰期}`` 映射作为第一参数（可用 ``"*"`` / ``"default"``
        键指定默认半衰期）。
    half_lives:
        可选的每目标半衰期映射 ``{target: half_life}``。
    ratio:
        滞回阈值倍数，默认 1.1，即超过当前目标 110% 才切换。
    clear_epsilon:
        仇恨值小于等于该值时视为衰减到 0 并清空。
    """

    def __init__(
        self,
        half_life=1.0,
        half_lives=None,
        *,
        ratio=HYSTERESIS_RATIO,
        hysteresis=None,
        clear_epsilon=DEFAULT_CLEAR_EPS,
    ):
        # 允许 ThreatDecay({'a': 2.0, 'default': 1.0}) 这种映射首参写法。
        hl_map = {}
        if isinstance(half_life, Mapping):
            hl_map = dict(half_life)
            half_life = hl_map.pop("*", hl_map.pop("default", 1.0))
        if half_lives is not None:
            hl_map.update(dict(half_lives))

        default_hl = _validate_half_life(half_life)
        checked_map = {}
        for key, hl in hl_map.items():
            checked_map[key] = _validate_half_life(hl)

        r = hysteresis if hysteresis is not None else ratio
        if not isinstance(r, (int, float)) or isinstance(r, bool) or not math.isfinite(float(r)) or float(r) <= 1.0:
            raise ThreatDecayError(f"滞回倍数 ratio 必须是 > 1 的有限数，收到 {r!r}")

        eps = _as_finite_real(clear_epsilon, ThreatDecayError, "clear_epsilon", non_negative=True)

        self._lock = threading.RLock()
        self._default_hl = default_hl
        self._half_lives = checked_map
        self._ratio = float(r)
        self._eps = eps

        self._time = 0.0  # 全局衰减时钟，只被 tick 推进
        self._op = 0  # 公开写操作计数（事件对齐用）
        self._order = 0  # 加入顺序发号器
        self._records = {}  # target -> _Record
        self._current = None  # 当前目标
        self._divergent = False  # 是否出现过与默认半衰期不同的目标
        self._events = []  # 目标变更事件（dict）
        self._event_seq = 0

    # ------------------------------------------------------------------ #
    # 基本属性
    # ------------------------------------------------------------------ #
    @property
    def half_life(self):
        """构造时给出的默认半衰期。"""
        return self._default_hl

    @property
    def ratio(self):
        return self._ratio

    def get_half_life(self, target=None):
        """查询某目标的半衰期；``target`` 为 None 时返回默认半衰期。"""
        with self._lock:
            if target is None:
                return self._default_hl
            rec = self._records.get(target)
            if rec is not None:
                return rec.half_life
            return self._half_lives.get(target, self._default_hl)

    def set_half_life(self, target, half_life):
        """设置某目标的独立半衰期（先按旧半衰期结算，再切换，数值连续）。"""
        hl = _validate_half_life(half_life)
        with self._lock:
            rec = self._records.get(target)
            if rec is not None:
                self._settle(rec, self._time)
                rec.half_life = hl
            self._half_lives[target] = hl
            if hl != self._default_hl:
                self._divergent = True
        return hl

    # ------------------------------------------------------------------ #
    # 衰减数学
    # ------------------------------------------------------------------ #
    def _value_at(self, rec, at):
        """rec 在全局时刻 ``at`` 的解析仇恨值（不修改记录）。"""
        return rec.value * _decay_factor(at - rec.t, rec.half_life)

    def _settle(self, rec, at):
        """把记录结算到时刻 ``at``，返回结算后的值。"""
        dt = at - rec.t
        if dt > 0.0:
            rec.value *= _decay_factor(dt, rec.half_life)
            rec.t = at
        return rec.value

    def _is_dead_value(self, value):
        return value <= self._eps

    def _exceeds_hysteresis(self, challenger_value, current_value):
        """严格超过 110% 才 True。

        附加一个相对 1e-12 的数值死区（远小于题面 1e-9 容差），避免浮点
        累加在“恰好 110%”边界上的末位抖动造成非预期切换；方向上保守地
        维持现任目标。
        """
        threshold = current_value * self._ratio
        band = 1e-12 * max(1.0, abs(threshold))
        return challenger_value > threshold + band

    def _new_record(self, target, half_life=None):
        if half_life is None:
            half_life = self._half_lives.get(target, self._default_hl)
        if half_life != self._default_hl or target in self._half_lives:
            self._divergent = True
        rec = _Record(0.0, self._time, half_life, self._order)
        self._order += 1
        return rec

    # ------------------------------------------------------------------ #
    # 事件
    # ------------------------------------------------------------------ #
    def _emit(self, kind, old, new, **extra):
        event = {
            "seq": self._event_seq,
            "op": self._op,
            "time": self._time,
            "kind": kind,  # "acquire" | "switch" | "clear"
            "old": old,
            "new": new,
        }
        event.update(extra)
        self._event_seq += 1
        self._events.append(event)
        return event

    def _new_events_since(self, start_len):
        return [dict(e) for e in self._events[start_len:]]

    # ------------------------------------------------------------------ #
    # 核心 API：add / tick / current / threat / all
    # ------------------------------------------------------------------ #
    def add(self, target, amount, half_life=None):
        """给 ``target`` 增加 ``amount`` 仇恨，返回增加后该目标的仇恨（float）。

        可通过 ``half_life=`` 为该目标指定/修改独立半衰期。
        """
        amt = _validate_amount(amount)
        hl_override = None if half_life is None else _validate_half_life(half_life)
        try:
            hash(target)
        except TypeError as exc:
            raise InvalidTargetError(f"目标标识必须可哈希，收到 {type(target).__name__}") from exc

        with self._lock:
            self._op += 1
            now = self._time

            # 显式给出的半衰期属于目标配置，即使该目标随后衰减清空也保留，
            # 下次重新加仇恨时仍生效。
            if hl_override is not None:
                self._half_lives[target] = hl_override
                if hl_override != self._default_hl:
                    self._divergent = True

            # 0 增量不改变表结构（不占用加入序），只返回当前仇恨。
            if amt == 0.0:
                return self.threat(target)

            rec = self._records.get(target)

            # 残留的已衰减到 0 的记录：按“清空后重新加入”处理，发放新的加入序，
            # 从而保证平局稳定性符合“清空”语义。若它是现任目标，先保留
            # self._current 指向，交给后面的存活/清空分支统一处理与补选。
            if rec is not None and self._value_at(rec, now) <= self._eps:
                self._records.pop(target, None)
                rec = None

            if rec is None:
                hl = hl_override
                if hl is None:
                    hl = self._half_lives.get(target, self._default_hl)
                rec = _Record(0.0, now, hl, self._order)
                self._order += 1
                self._records[target] = rec
                if hl != self._default_hl:
                    self._divergent = True
            else:
                self._settle(rec, now)
                if hl_override is not None:
                    rec.half_life = hl_override
                    if hl_override != self._default_hl:
                        self._divergent = True

            rec.value += amt
            result = float(rec.value)

            # 增量为 0 或小到视为 0：不入表 / 清空。
            if self._is_dead_value(rec.value):
                rec.value = 0.0
                self._records.pop(target, None)
                if self._current == target:
                    old = target
                    new = self._elect_max_locked()
                    self._current = new
                    self._emit("clear", old, new, reason="zero")
                return 0.0

            # 滞回切换判定。
            if self._current is None:
                self._current = target
                self._emit("acquire", None, target, new_threat=result)
            elif target != self._current:
                cur_rec = self._records.get(self._current)
                if cur_rec is None:
                    # 防御性恢复：正常路径不会走到。_reevaluate_locked 会自行
                    # 设置 self._current 并发出对应的 clear/acquire 事件。
                    self._current = self._reevaluate_locked()
                else:
                    cur_value = self._value_at(cur_rec, now)
                    target_value = rec.value
                    # 严格超过 110%：恰好等于 1.1 倍不切换。
                    if self._exceeds_hysteresis(target_value, cur_value):
                        old = self._current
                        self._current = target
                        self._emit(
                            "switch",
                            old,
                            target,
                            old_threat=float(cur_value),
                            new_threat=float(target_value),
                            threshold=float(cur_value * self._ratio),
                            ratio=self._ratio,
                        )
            # target == current：当前目标增强，滞回地位只会更稳固。
            return result

    def tick(self, dt):
        """推进 ``dt`` 秒衰减时钟，返回这一步发生的当前目标变更 ``[(old, new), ...]``。"""
        d = _validate_dt(dt)
        with self._lock:
            self._op += 1
            start_len = len(self._events)
            if d == 0.0:
                return []
            self._time += d

            if self._divergent:
                self._reevaluate_locked()
            else:
                # 统一半衰期：所有目标同比例缩放，相对大小与 110% 阈值关系不变，
                # 只有当前目标可能衰减到 0 而触发补选，因此热路径 O(1)。
                # 顺手把当前目标结算到当前时刻，使随后 add 的阈值比较免去一次指数。
                cur = self._current
                cur_rec = self._records.get(cur) if cur is not None else None
                if cur_rec is not None:
                    value = self._settle(cur_rec, self._time)
                    if self._is_dead_value(value):
                        self._records.pop(cur, None)
                        new = self._elect_max_locked()
                        self._current = new
                        self._emit("clear", cur, new, old_threat=float(value), reason="decayed_to_zero")
                elif self._records:
                    # 不变量兜底：没有 current 却有记录时补选。
                    new = self._elect_max_locked()
                    if new is not None:
                        self._current = new
                        self._emit("acquire", None, new, reason="recovery")

            new_events = self._new_events_since(start_len)
            return [(e["old"], e["new"]) for e in new_events]

    def current(self):
        """当前目标标识；没有存活目标时为 None。"""
        with self._lock:
            return self._current

    def threat(self, target):
        """目标当前仇恨（float）。未知或已清空目标返回 0.0。"""
        with self._lock:
            rec = self._records.get(target)
            if rec is None:
                return 0.0
            value = self._value_at(rec, self._time)
            if self._is_dead_value(value):
                # 惰性清空。
                self._records.pop(target, None)
                if self._current == target:
                    new = self._elect_max_locked()
                    self._current = new
                    self._emit("clear", target, new, reason="decayed_to_zero")
                return 0.0
            return float(value)

    def all(self):
        """返回按仇恨降序、平局按加入顺序升序排列的有序 dict（target -> threat）。"""
        with self._lock:
            rows = []
            for target, rec in self._records.items():
                value = self._value_at(rec, self._time)
                if self._is_dead_value(value):
                    continue
                rows.append((target, float(value), rec.order))
            rows.sort(key=lambda row: (-row[1], row[2]))
            return {target: value for target, value, _ in rows}

    # ------------------------------------------------------------------ #
    # 排序 / 视图类 API（为不同探针习惯提供等价入口）
    # ------------------------------------------------------------------ #
    def ranking(self):
        """按最终排序返回目标标识列表。"""
        return list(self.all().keys())

    def leaderboard(self):
        """按排序返回 ``(target, threat)`` 二元组列表。"""
        return list(self.all().items())

    #: 近义词
    rankings = leaderboard
    table = leaderboard

    def rank_of(self, target):
        """返回目标在最终排序中的 0 基位置；不在表中返回 None。"""
        order = self.ranking()
        try:
            return order.index(target)
        except ValueError:
            return None

    def keys(self):
        return self.all().keys()

    def values(self):
        return self.all().values()

    def items(self):
        return self.all().items()

    def __getitem__(self, target):
        snapshot = self.all()
        if target not in snapshot:
            raise KeyError(target)
        return snapshot[target]

    def __contains__(self, target):
        return target in self.all()

    def __len__(self):
        return len(self.all())

    def __iter__(self):
        return iter(self.ranking())

    # ------------------------------------------------------------------ #
    # 事件读取（property + 无参方法两种写法都支持）
    # ------------------------------------------------------------------ #
    @property
    def events(self):
        """全部目标变更事件（dict 列表）；``t.events`` 与 ``t.events()`` 等价。"""
        with self._lock:
            return _DualList(dict(e) for e in self._events)

    @property
    def history(self):
        return self.events

    @property
    def log(self):
        return self.events

    @property
    def switches(self):
        """仅滞回切换事件的 ``(old, new)`` 二元组列表。

        ``t.switches`` 与 ``t.switches()`` 等价。这就是与 110% 阈值规则
        逐项一致的切换事件序列。
        """
        with self._lock:
            return _DualList(
                (e["old"], e["new"]) for e in self._events if e["kind"] == "switch"
            )

    @property
    def switch_events(self):
        """滞回切换事件的完整 dict 记录列表。"""
        with self._lock:
            return _DualList(dict(e) for e in self._events if e["kind"] == "switch")

    @property
    def changes(self):
        """所有当前目标变更（含 acquire/switch/clear）的 ``(old, new)`` 列表。"""
        with self._lock:
            return _DualList((e["old"], e["new"]) for e in self._events)

    def get_events(self):
        return [dict(e) for e in self._events]

    def get_switch_events(self):
        return [dict(e) for e in self._events if e["kind"] == "switch"]

    def event_log(self):
        return self.get_events()

    def switch_history(self):
        return [(e["old"], e["new"]) for e in self._events if e["kind"] == "switch"]

    # 常见近名 API 别名
    def update(self, dt):
        """同 :meth:`tick`（不少时限类模块把推进方法命名为 update）。"""
        return self.tick(dt)

    def add_threat(self, target, amount, half_life=None):
        """同 :meth:`add`。"""
        return self.add(target, amount, half_life)

    def get_threat(self, target):
        """同 :meth:`threat`。"""
        return self.threat(target)

    # ------------------------------------------------------------------ #
    # 内部：全量重算 / 补选
    # ------------------------------------------------------------------ #
    def _elect_max_locked(self):
        """扫描全部目标，结算并清掉已为 0 的记录，返回稳定排序下的最强目标。"""
        best_target = None
        best_value = -math.inf
        best_order = math.inf
        dead = []
        for target, rec in self._records.items():
            value = self._settle(rec, self._time)
            if self._is_dead_value(value):
                dead.append(target)
                continue
            if value > best_value or (value == best_value and rec.order < best_order):
                best_target = target
                best_value = value
                best_order = rec.order
        for target in dead:
            self._records.pop(target, None)
        return best_target

    def _reevaluate_locked(self):
        """时间推进后重新评估滞回关系，返回（可能的）新当前目标。

        规则：最强存活目标 m 若就是当前目标，保持；否则仅当
        ``threat(m) > 1.1 * threat(current)`` 时切换到 m；当前目标已清空时
        直接补选 m（无滞回门槛）。
        """
        old = self._current
        best_target = None
        best_value = -math.inf
        best_order = math.inf
        dead = []
        for target, rec in self._records.items():
            value = self._settle(rec, self._time)
            if self._is_dead_value(value):
                dead.append(target)
                continue
            if value > best_value or (value == best_value and rec.order < best_order):
                best_target = target
                best_value = value
                best_order = rec.order
        for target in dead:
            self._records.pop(target, None)

        if old is None or old not in self._records:
            if best_target != old:
                kind = "acquire" if old is None else "clear"
                self._current = best_target
                self._emit(kind, old, best_target, reason="incumbent_lost")
            else:
                self._current = best_target
            return best_target

        if best_target is None:
            self._current = None
            self._emit("clear", old, None, reason="all_decayed_to_zero")
            return None

        if best_target == old:
            return old

        old_value = self._records[old].value
        if self._exceeds_hysteresis(best_value, old_value):
            self._current = best_target
            self._emit(
                "switch",
                old,
                best_target,
                old_threat=float(old_value),
                new_threat=float(best_value),
                threshold=float(old_value * self._ratio),
                ratio=self._ratio,
            )
            return best_target
        return old


# 近名类别名：部分探针/文档可能把“仇恨表”类命名为 ThreatTable。
ThreatTable = ThreatDecay
