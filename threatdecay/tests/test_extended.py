"""题面约束的扩展验证（确定性部分）。

严格的 300ms 性能口径用 ``python bench.py`` 单独测量；这里只放一个非常宽松的
性能回归护栏，避免并行评测机高负载时把验收命令跑红。
"""

import math
import threading
import time

import pytest

import threatdecay
from threatdecay import (
    ThreatDecay,
    ThreatDecayError,
    InvalidHalfLifeError,
    InvalidThreatAmountError,
    InvalidDeltaError,
)

LN2 = math.log(2.0)


def analytic(v0, dt, hl):
    return v0 * math.exp(-LN2 * dt / hl)


# ----------------------------------------------------------- 解析式衰减 ≤1e-9
@pytest.mark.parametrize("hl", [0.1, 0.5, 1.0, 2.0, 3.333, 7.0])
@pytest.mark.parametrize("dt", [0.0, 0.1, 1.0, 2.5, 5.0, 20.0])
def test_decay_matches_analytic(hl, dt):
    t = ThreatDecay(hl)
    t.add("a", 10.0)
    t.tick(dt)
    assert abs(t.threat("a") - analytic(10.0, dt, hl)) <= 1e-9


def test_segmented_tick_matches_whole_within_tol():
    whole = ThreatDecay(2.0)
    whole.add("a", 10.0)
    whole.tick(3.7)

    seg = ThreatDecay(2.0)
    seg.add("a", 10.0)
    for d in (0.3, 0.7, 1.1, 1.6):
        seg.tick(d)
    assert abs(whole.threat("a") - seg.threat("a")) <= 1e-9


def test_increments_at_different_times_match_sum():
    t = ThreatDecay(1.0)
    parts = []
    clock = 0.0
    for amt, wait in [(4.0, 0.0), (6.0, 0.5), (2.5, 1.25), (7.0, 0.1)]:
        t.tick(wait)
        clock += wait
        t.add("a", amt)
        parts.append((amt, clock))
    t.tick(2.0)
    clock += 2.0
    expected = sum(analytic(a, clock - at, 1.0) for a, at in parts)
    assert abs(t.threat("a") - expected) <= 1e-9


# ----------------------------------------------------------- 每目标独立半衰期
def test_per_target_half_life():
    t = ThreatDecay(1.0)
    t.add("fast", 8.0, half_life=1.0)
    t.add("slow", 8.0, half_life=4.0)
    t.tick(4.0)
    assert abs(t.threat("fast") - 0.5) <= 1e-9
    assert abs(t.threat("slow") - 4.0) <= 1e-9
    assert t.get_half_life("slow") == 4.0


def test_constructor_half_lives_mapping():
    t = ThreatDecay(1.0, half_lives={"a": 2.0})
    t.add("a", 8.0)
    t.tick(2.0)
    assert abs(t.threat("a") - 4.0) <= 1e-9


def test_set_half_life_is_continuous():
    t = ThreatDecay(1.0)
    t.add("a", 8.0)
    t.tick(1.0)
    value = t.threat("a")
    t.set_half_life("a", 2.0)
    t.tick(2.0)
    assert abs(t.threat("a") - value * 0.5) <= 1e-9


# ----------------------------------------------------------- 110% 滞回与事件序列
def test_hysteresis_boundary_is_strict():
    def cur(b):
        t = ThreatDecay(1.0)
        t.add("a", 10.0)
        t.add("b", b)
        return t.current()

    assert cur(10.5) == "a"
    assert cur(10.999999) == "a"
    assert cur(11.0) == "a"          # 恰好 110%：“超过”才切，故不切
    assert cur(11.0000001) == "b"
    assert cur(12.0) == "b"


def test_threshold_rebased_on_new_current():
    t = ThreatDecay(1.0)
    t.add("a", 10.0)
    t.add("b", 12.0)
    assert t.current() == "b"
    t.add("c", 13.1)                 # 12 * 1.1 = 13.2，未超过
    assert t.current() == "b"
    t.add("c", 0.2)                  # 13.3 > 13.2
    assert t.current() == "c"


def test_switch_event_sequence():
    t = ThreatDecay(1.0)
    t.add("a", 10.0)
    t.add("b", 10.5)                 # 不切
    t.add("b", 1.0)                  # 11.5 > 11 -> a->b
    t.add("c", 20.0)                 # -> c
    assert list(t.switches) == [("a", "b"), ("b", "c")]
    assert [e["kind"] for e in t.events] == ["acquire", "switch", "switch"]
    # property 与无参方法两种写法等价
    assert t.switches() == t.switches
    assert len(t.events()) == 3


def test_tick_returns_change_pairs():
    t = ThreatDecay(1.0)
    t.add("a", 1.0)
    t.tick(100.0)
    assert t.current() is None
    assert t.tick(1.0) == []


# ----------------------------------------------------------- 衰减到 0 后清空
def test_clear_after_huge_tick():
    t = ThreatDecay(1.0)
    t.add("a", 1.0)
    t.tick(100.0)
    assert t.current() is None
    assert t.all() == {}
    assert "a" not in t
    assert t.threat("a") == 0.0
    assert isinstance(t.threat("a"), float)


def test_incumbent_expiry_elects_survivor():
    t = ThreatDecay(1.0, half_lives={"a": 0.5, "b": 100.0})
    t.add("a", 10.0)
    t.add("b", 1.0)
    t.tick(60.0)
    assert t.current() == "b"


def test_readd_after_clear_gets_fresh_insertion_order():
    t = ThreatDecay(1.0)
    t.add("a", 1.0)
    t.tick(100.0)
    t.add("b", 1.0)
    t.add("a", 1.0)
    assert t.ranking() == ["b", "a"]


# ----------------------------------------------------------- 累加与稳定排序
def test_sequential_accumulation():
    t = ThreatDecay(1.0)
    t.add("a", 3.0)
    t.add("a", 4.0)
    assert t.threat("a") == 7.0


def test_stable_tie_order_is_insertion_order():
    t = ThreatDecay(1.0)
    for name in ("c", "a", "b"):
        t.add(name, 5.0)
    assert t.ranking() == ["c", "a", "b"]
    t.add("a", 3.0)
    assert t.ranking() == ["a", "c", "b"]
    board = t.leaderboard()
    assert [name for name, _ in board] == ["a", "c", "b"]


def test_all_is_sorted_mapping():
    t = ThreatDecay(1.0)
    t.add("low", 1.0)
    t.add("high", 9.0)
    assert isinstance(t.all(), dict)
    assert list(t.all()) == ["high", "low"]
    assert t["high"] > t["low"]
    assert len(t) == 2


# ----------------------------------------------------------- 非法输入可区分报错
@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), "1"])
def test_invalid_half_life(bad):
    with pytest.raises(InvalidHalfLifeError):
        ThreatDecay(bad)
    with pytest.raises(ValueError):
        ThreatDecay(bad)


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), "x"])
def test_invalid_amount(bad):
    with pytest.raises(InvalidThreatAmountError):
        ThreatDecay(1.0).add("a", bad)


@pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf"), "x"])
def test_invalid_dt(bad):
    with pytest.raises(InvalidDeltaError):
        ThreatDecay(1.0).tick(bad)


def test_exception_types_are_distinct():
    assert len({InvalidHalfLifeError, InvalidThreatAmountError, InvalidDeltaError}) == 3
    for cls in (InvalidHalfLifeError, InvalidThreatAmountError, InvalidDeltaError):
        assert issubclass(cls, ThreatDecayError)
        assert issubclass(cls, ValueError)


def test_zero_amount_and_zero_dt_are_legal():
    t = ThreatDecay(1.0)
    assert t.add("a", 0.0) == 0.0
    t.tick(0.0)
    assert t.current() is None


# ----------------------------------------------------------- 类型契约
def test_return_types():
    t = ThreatDecay(1.0)
    assert t.current() is None
    assert isinstance(t.threat("missing"), float)
    assert isinstance(t.add("a", 1.0), float)
    assert isinstance(t.threat("a"), float)
    assert isinstance(t.current(), str)
    assert isinstance(t.all(), dict)


# ----------------------------------------------------------- 并发：共享实例不丢增量
def test_concurrent_adds_no_lost_update():
    t = ThreatDecay(1.0)
    n_threads, per = 8, 12500
    barrier = threading.Barrier(n_threads)

    def worker():
        barrier.wait()
        for _ in range(per):
            t.add("a", 1.0)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    # 每次 +1.0 在整数浮点上精确，故总和可精确相等
    assert t.threat("a") == float(n_threads * per)


# ----------------------------------------------------------- 性能回归的宽松护栏
def test_100k_ops_loose_guard():
    t = ThreatDecay(1.0)
    for i in range(20):
        t.add("e%d" % i, 5.0)
    start = time.perf_counter()
    for i in range(100_000):
        t.add("e%d" % (i % 20), 0.7)
        t.tick(0.01)
        t.current()
    elapsed = time.perf_counter() - start
    # 题面口径是 300ms（严格测量见 bench.py）；这里放到 2s 防止高负载误报。
    assert elapsed < 2.0, elapsed
