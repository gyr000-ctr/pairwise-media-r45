import math

import pytest

import combatframe

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

M = {"jab": (3, 2, 5), "kick": (6, 3, 6)}


def _c():
    return combatframe.CombatFrame(M)

CASES = [
    ("total", lambda: _c().total('jab') == 10),
    ("window", lambda: _c().window('jab', 'active') == (3, 5)),
    ("startup", lambda: _c().window('jab', 'startup') == (0, 3)),
    ("recovery", lambda: _c().window('jab', 'recovery') == (5, 10)),
    ("cancel_ok", lambda: _c().can_cancel('jab', 'kick', 3) is True),
    ("cancel_early", lambda: _c().can_cancel('jab', 'kick', 2) is False),
    ("overlap", lambda: _c().overlap('jab', 'kick') is False),
    ("bad_moves", lambda: _raises(lambda: combatframe.CombatFrame({}))),
    ("bad_frames", lambda: _raises(lambda: combatframe.CombatFrame({'x': (0, 1, 1)}))),
    ("bad_name", lambda: _raises(lambda: _c().total('zz'))),
    ("bad_kind", lambda: _raises(lambda: _c().window('jab', 'bogus'))),
    ("type", lambda: isinstance(_c().window('jab', 'active'), tuple)),
    ("det", lambda: _c().overlap('jab', 'kick') == _c().overlap('jab', 'kick')),
    ("frame_neg", lambda: _raises(lambda: _c().can_cancel('jab', 'kick', -1))),
    ("self_cancel", lambda: _c().can_cancel('jab', 'jab', 3) is False),
]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    assert check() is True
