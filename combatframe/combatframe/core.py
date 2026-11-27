"""combatframe 核心 API（仅使用 Python 标准库）。

数据模型
========
招式表 ``{招式名: 帧数据}``，帧数据支持三种写法：

1. ``(startup, active, recovery)``                       —— 三元组
2. ``(startup, active, recovery, total)``                —— 附带声明总帧数
3. ``{"startup": s, "active": a, "recovery": r}``        —— 映射（可带 "total"）

起手 / 判定 / 收招帧数必须为有限正数（bool 除外）；``total`` 若给出，
必须与三者之和一致（逐招校验，容差 ``1e-12``）。非法帧数可区分报错：
帧数为 0 抛 :class:`ZeroFrameError`，为负抛 :class:`NegativeFrameError`，
二者均为 :class:`InvalidFramesError` 的子类。

帧区间
======
所有帧区间均为**半开区间** ``[start, end)``：

* 起手 ``startup``  : ``[0, startup)``
* 判定 ``active``   : ``[startup, startup + active)``
* 收招 ``recovery`` : ``[startup + active, total)``

判定段重叠与区间相交的定义严格一致：两个半开区间
``[a0, a1)`` 与 ``[b0, b1)`` 相交当且仅当 ``max(a0, b0) < min(a1, b1)``。
同一招式与自身比较也遵循该定义（判定段非空，因此返回 ``True``）。

取消窗口
========
取消窗口默认等于判定段。也可以通过构造参数 ``cancel_windows`` 配置
``{招式名: end}`` / ``{招式名: (start, end)}``：``start`` 必须等于该招
判定段起点（"只能从判定段起点开始"），``end`` 不得越过总帧数，否则抛
:class:`InvalidCancelWindowError`。``can_cancel(a, b, frame)`` 当且仅当
``frame`` 落在 ``a`` 的取消窗口内、且 ``a != b`` 时返回 ``True``；
合法性判定即区间代数 ``start <= frame < end``，同一查询结果恒定。

复杂度
======
构造时一次性校验并缓存各区间，单次 ``can_cancel`` / ``overlap`` 为
O(1) 字典查找加常数次比较，10 万次判定远低于 300 ms。
"""

import math

__all__ = [
    "CombatFrame",
    "CombatFrameError",
    "InvalidFramesError",
    "ZeroFrameError",
    "NegativeFrameError",
    "UnknownMoveError",
    "InvalidKindError",
    "InvalidFrameError",
    "InvalidCancelWindowError",
]

# 浮点一致性容差（题面要求 <= 1e-12）
EPS = 1e-12

# window() 支持的区间种类
_WINDOW_KINDS = ("startup", "active", "recovery")

# 缓存元组中的下标（提升 10 万次判定的性能）
_S_STARTUP = 0
_S_ACTIVE = 1
_S_RECOVERY = 2
_S_TOTAL = 3
_S_ACTIVE_START = 4
_S_ACTIVE_END = 5
_S_CANCEL_START = 6
_S_CANCEL_END = 7


class CombatFrameError(ValueError):
    """combatframe 所有可区分错误的基类（同时是 ValueError）。"""


class InvalidFramesError(CombatFrameError):
    """招式帧数据非法（结构错误、非数值、NaN/Inf、总帧数不符等）。"""


class ZeroFrameError(InvalidFramesError):
    """帧数为 0。"""


class NegativeFrameError(InvalidFramesError):
    """帧数为负。"""


class UnknownMoveError(CombatFrameError):
    """请求了不存在的招式。"""

    def __init__(self, name, message=None):
        self.name = name
        super().__init__(
            message if message is not None else f"unknown move: {name!r}"
        )


class InvalidKindError(CombatFrameError):
    """window() 的区间种类非法。"""

    def __init__(self, kind, message=None):
        self.kind = kind
        super().__init__(
            message if message is not None
            else f"invalid window kind: {kind!r}; expected one of {_WINDOW_KINDS}"
        )


class InvalidFrameError(CombatFrameError):
    """查询帧非法（负数、NaN/Inf、非数值、bool 等）。"""

    def __init__(self, frame, message=None):
        self.frame = frame
        super().__init__(
            message if message is not None else f"invalid frame: {frame!r}"
        )


class InvalidCancelWindowError(CombatFrameError):
    """取消窗口配置越界：起点不在判定段起点，或终点越过总帧数。"""


# ---------------------------------------------------------------------- #
# 数值校验辅助
# ---------------------------------------------------------------------- #
def _is_real(v):
    """有限实数（排除 bool、NaN、Inf 与非数值）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if isinstance(v, float):
        return math.isfinite(v)
    return True


def _close(a, b):
    """绝对/相对混合容差比较，满足题面 <= 1e-12 的一致性要求。"""
    return abs(a - b) <= EPS or abs(a - b) <= EPS * max(1.0, abs(a), abs(b))


def _parse_frames(name, spec):
    """解析并校验单招帧数据，返回 (startup, active, recovery, declared_total)。"""
    declared_total = None
    if isinstance(spec, dict):
        missing = [k for k in _WINDOW_KINDS if k not in spec]
        if missing:
            raise InvalidFramesError(
                f"move {name!r}: missing frame fields: {', '.join(missing)}"
            )
        startup, active, recovery = (spec[k] for k in _WINDOW_KINDS)
        if "total" in spec:
            declared_total = spec["total"]
    else:
        if isinstance(spec, (str, bytes)):
            raise InvalidFramesError(
                f"move {name!r}: frame data must be a sequence of numbers"
            )
        try:
            seq = tuple(spec)
        except TypeError:
            raise InvalidFramesError(
                f"move {name!r}: frame data must be a sequence of numbers"
            ) from None
        if len(seq) == 3:
            startup, active, recovery = seq
        elif len(seq) == 4:
            startup, active, recovery, declared_total = seq
        else:
            raise InvalidFramesError(
                f"move {name!r}: expected 3 or 4 frame counts, got {len(seq)}"
            )

    for label, value in (
        ("startup", startup),
        ("active", active),
        ("recovery", recovery),
    ):
        if not _is_real(value):
            raise InvalidFramesError(
                f"move {name!r}: {label} must be a finite number, got {value!r}"
            )
        # bool 已被 _is_real 排除
        if value == 0:
            raise ZeroFrameError(
                f"move {name!r}: {label} frame count must be positive, got 0"
            )
        if value < 0:
            raise NegativeFrameError(
                f"move {name!r}: {label} frame count must be positive, got {value!r}"
            )

    if declared_total is not None:
        if not _is_real(declared_total):
            raise InvalidFramesError(
                f"move {name!r}: total must be a finite number, got {declared_total!r}"
            )
        computed = startup + active + recovery
        if not _close(computed, declared_total):
            raise InvalidFramesError(
                f"move {name!r}: startup+active+recovery={computed!r} "
                f"does not equal declared total {declared_total!r}"
            )

    return startup, active, recovery, declared_total


def _validate_query_frame(frame):
    """校验取消查询帧，返回其数值。"""
    if not _is_real(frame):
        raise InvalidFrameError(frame)
    if frame < 0:
        raise InvalidFrameError(
            frame, f"frame must be non-negative, got {frame!r}"
        )
    return frame


class CombatFrame:
    """战斗帧数据与取消窗口。"""

    # ------------------------------------------------------------------ #
    # 构造
    # ------------------------------------------------------------------ #
    def __init__(self, moves, cancel_windows=None):
        """构造招式表并校验帧数据与取消窗口配置。

        Parameters
        ----------
        moves:
            非空映射 ``{name: frames}``，格式见模块文档。
        cancel_windows:
            可选的取消窗口配置 ``{name: end}`` 或 ``{name: (start, end)}``；
            默认（未配置）取消窗口等于判定段。
        """
        if not isinstance(moves, dict):
            raise InvalidFramesError("moves must be a dict of {name: frame data}")
        if not moves:
            raise InvalidFramesError("moves must not be empty")

        specs = {}
        for name, spec in moves.items():
            startup, active, recovery, _declared = _parse_frames(name, spec)
            total = startup + active + recovery
            active_start = startup
            active_end = startup + active
            specs[name] = (
                startup,
                active,
                recovery,
                total,
                active_start,
                active_end,
                active_start,          # 默认取消窗口 = 判定段
                active_end,
            )

        if cancel_windows is not None:
            self._apply_cancel_windows(specs, cancel_windows)

        # 冻结缓存，保证多次查询结果恒定
        self._specs = specs
        self._names = frozenset(specs)

    @staticmethod
    def _apply_cancel_windows(specs, cancel_windows):
        """校验并写入取消窗口配置（原地修改 specs）。"""
        if not isinstance(cancel_windows, dict):
            raise InvalidCancelWindowError(
                "cancel_windows must be a dict of {name: end} or {name: (start, end)}"
            )
        for name, cfg in cancel_windows.items():
            if name not in specs:
                raise UnknownMoveError(name)
            spec = specs[name]
            startup = spec[_S_STARTUP]
            total = spec[_S_TOTAL]

            if isinstance(cfg, dict):
                if "end" not in cfg:
                    raise InvalidCancelWindowError(
                        f"cancel window for {name!r}: missing 'end'"
                    )
                start = cfg.get("start", startup)
                end = cfg["end"]
            elif isinstance(cfg, (tuple, list)):
                if len(cfg) == 1:
                    start, end = startup, cfg[0]
                elif len(cfg) == 2:
                    start, end = cfg
                else:
                    raise InvalidCancelWindowError(
                        f"cancel window for {name!r}: expected 1 or 2 values"
                    )
            else:
                start, end = startup, cfg

            if not _is_real(start) or not _is_real(end):
                raise InvalidCancelWindowError(
                    f"cancel window for {name!r} must be finite numbers, "
                    f"got {(start, end)!r}"
                )
            # 取消窗口只能从判定段起点开始
            if not _close(start, startup):
                raise InvalidCancelWindowError(
                    f"cancel window for {name!r} must start at active start "
                    f"{startup!r}, got {start!r}"
                )
            # 越界配置报错
            if end < start or end > total + EPS * max(1.0, abs(total)):
                raise InvalidCancelWindowError(
                    f"cancel window for {name!r} out of bounds: "
                    f"end {end!r} not in [{start!r}, {total!r}]"
                )

            specs[name] = spec[:_S_CANCEL_START] + (start, end)

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def _spec(self, name):
        try:
            return self._specs[name]
        except (KeyError, TypeError):
            raise UnknownMoveError(name) from None

    def total(self, name):
        """总帧数 = 起手 + 判定 + 收招。"""
        return self._spec(name)[_S_TOTAL]

    def window(self, name, kind):
        """帧窗口，半开区间 ``(start, end)``。

        ``kind`` 取 ``"startup"`` / ``"active"`` / ``"recovery"``。
        """
        spec = self._spec(name)
        if kind == "startup":
            return (0, spec[_S_STARTUP])
        if kind == "active":
            return (spec[_S_ACTIVE_START], spec[_S_ACTIVE_END])
        if kind == "recovery":
            return (spec[_S_ACTIVE_END], spec[_S_TOTAL])
        raise InvalidKindError(kind)

    def cancel_window(self, name):
        """取消窗口，半开区间 ``(start, end)``。"""
        spec = self._spec(name)
        return (spec[_S_CANCEL_START], spec[_S_CANCEL_END])

    def overlap(self, a, b):
        """两招判定段是否重叠（半开区间相交定义）。"""
        sa = self._spec(a)
        sb = self._spec(b)
        a0, a1 = sa[_S_ACTIVE_START], sa[_S_ACTIVE_END]
        b0, b1 = sb[_S_ACTIVE_START], sb[_S_ACTIVE_END]
        return max(a0, b0) < min(a1, b1)

    def can_cancel(self, a, b, frame):
        """``a`` 能否在第 ``frame`` 帧取消并接 ``b``。

        当且仅当 ``frame`` 落在 ``a`` 的取消窗口 ``[start, end)`` 内、
        且 ``a`` 与 ``b`` 不是同一招时返回 ``True``。
        """
        sa = self._spec(a)
        self._spec(b)  # 校验目标招式存在
        f = _validate_query_frame(frame)
        if a == b:
            return False
        return sa[_S_CANCEL_START] <= f < sa[_S_CANCEL_END]
