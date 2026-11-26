import math

import pytest

import spawnwave

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def _norm(v):
    return math.sqrt(sum(c * c for c in v))

CURVE = lambda n: 10 + 5 * n
COST = {"grunt": 1, "elite": 5}

def _s():
    return spawnwave.SpawnWave(CURVE, COST, 1)

CASES = [
    ("budget", lambda: _s().budget(1) >= 0.0),
    ("wave", lambda: isinstance(_s().wave(1), dict)),
    ("within_budget", lambda: sum(v * COST[k] for k, v in _s().wave(1).items()) <= _s().budget(1) + 1e-9),
    ("monotone", lambda: _s().budget(1) <= _s().budget(2)),
    ("det", lambda: _s().wave(2) == _s().wave(2)),
    ("seed_diff", lambda: _s().wave(2) != spawnwave.SpawnWave(CURVE, COST, 2).wave(2)),
    ("bad_budget", lambda: _raises(lambda: spawnwave.SpawnWave(lambda n: -1.0, COST, 1).wave(1))),
    ("bad_costs", lambda: _raises(lambda: spawnwave.SpawnWave(CURVE, {}, 1))),
    ("bad_n", lambda: _raises(lambda: _s().wave(0))),
    ("type", lambda: isinstance(_s().wave(1), dict)),
    ("budget_type", lambda: isinstance(_s().budget(1), float)),
    ("no_mut", lambda: _s().wave(1) is not None),
    ("nan", lambda: _raises(lambda: spawnwave.SpawnWave(lambda n: float('nan'), COST, 1).wave(1))),
    ("count_int", lambda: all(isinstance(v, int) for v in _s().wave(1).values())),
    ("curve_growth", lambda: _s().budget(3) > _s().budget(1)),
]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    assert check() is True
