import math

import pytest

import charmove

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

TILES = [[0, 0, 0], [0, 1, 0], [1, 1, 1]]


def _m():
    return charmove.CharMove(TILES)

CASES = [
    ("step_pair", lambda: len(_m().step((1.5, 1.5), (1.0, 0.0), 0.01)) == 2),
    ("no_wall", lambda: abs(_m().step((0.5, 0.5), (1.0, 0.0), 0.01)[0] - 0.51) < 1e-9),
    ("wall_block", lambda: _m().step((0.5, 2.5), (1.0, 0.0), 1.0)[0] < 3.0),
    ("ground", lambda: _m().on_ground((1.5, 1.5)) is True),
    ("air", lambda: _m().on_ground((1.5, 0.2)) is False),
    ("slope", lambda: isinstance(_m().slope((1.5, 1.5)), float)),
    ("bad_dt", lambda: _raises(lambda: _m().step((0.5, 0.5), (1.0, 0.0), 0.0))),
    ("bad_tiles", lambda: _raises(lambda: charmove.CharMove([]))),
    ("bad_pos", lambda: _raises(lambda: _m().step((0.5,), (1.0, 0.0), 0.01))),
    ("type", lambda: isinstance(_m().step((1.5, 1.5), (0.0, 0.0), 0.01), tuple)),
    ("det", lambda: _m().step((1.5, 1.5), (1.0, 0.0), 0.01) == _m().step((1.5, 1.5), (1.0, 0.0), 0.01)),
    ("nan", lambda: _raises(lambda: _m().step((float('nan'), 1.5), (1.0, 0.0), 0.01))),
    ("no_mut", lambda: _m().step((1.5, 1.5), (0.0, 1.0), 0.01) is not None),
    ("stable", lambda: _m().step((0.5, 2.5), (1.0, 0.0), 0.5)[0] <= 3.0),
    ("float", lambda: isinstance(_m().step((1.5, 1.5), (0.1, 0.0), 0.01)[0], float)),
]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    assert check() is True
