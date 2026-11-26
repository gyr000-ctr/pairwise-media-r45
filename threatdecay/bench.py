"""题面性能口径：10 万次操作不超过 300ms。

用法：``python bench.py``。会分别测量几种典型 10 万次操作组合，
任一组合超过 300ms 则以非零状态退出。仅使用标准库。
"""

import time

from threatdecay import ThreatDecay

LIMIT_MS = 300.0
N = 100_000


def bench_add_rotation():
    t = ThreatDecay(1.0)
    for i in range(N):
        t.add("e%d" % (i % 20), 1.0)


def bench_add_distinct():
    t = ThreatDecay(1.0)
    for i in range(N):
        t.add("e%d" % i, 1.0)


def bench_tick():
    t = ThreatDecay(1.0)
    for i in range(20):
        t.add("e%d" % i, 10.0)
    for _ in range(N):
        t.tick(0.01)


def bench_mix():
    t = ThreatDecay(1.0)
    for i in range(20):
        t.add("e%d" % i, 5.0)
    for i in range(N):
        t.add("e%d" % (i % 20), 0.7)
        t.tick(0.01)
        t.current()


def main():
    cases = [
        ("add 轮转 20 目标", bench_add_rotation),
        ("add 10 万不同目标", bench_add_distinct),
        ("tick 10 万次(20 目标)", bench_tick),
        ("add+tick+current 混合", bench_mix),
    ]
    worst = 0.0
    for name, fn in cases:
        fn()  # 预热
        start = time.perf_counter()
        fn()
        ms = (time.perf_counter() - start) * 1000.0
        worst = max(worst, ms)
        flag = "OK " if ms <= LIMIT_MS else "FAIL"
        print(f"[{flag}] {name}: {ms:6.1f} ms (限 {LIMIT_MS:.0f} ms)")
    if worst > LIMIT_MS:
        raise SystemExit(f"性能不达标：最差 {worst:.1f} ms > {LIMIT_MS:.0f} ms")
    print(f"\n全部 < {LIMIT_MS:.0f} ms，最差 {worst:.1f} ms")


if __name__ == "__main__":
    main()
