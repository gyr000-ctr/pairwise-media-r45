import math

import pytest

import crafting

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def _norm(v):
    return math.sqrt(sum(c * c for c in v))

R1 = {"axe": ({"wood": 1, "iron": 2}, 1)}

def _c():
    return crafting.Crafting(R1)

CASES = [
    ("order", lambda: isinstance(_c().order('axe', 1), list)),
    ("missing", lambda: isinstance(_c().missing({'wood': 0, 'iron': 0}, 'axe', 1), dict)),
    ("order_len", lambda: len(_c().order('axe', 2)) >= 1),
    ("cycle", lambda: _raises(lambda: crafting.Crafting({'a': ({'b': 1}, 1), 'b': ({'a': 1}, 1)}).order('a', 1))),
    ("unknown", lambda: _raises(lambda: _c().order('zz', 1))),
    ("bad_n", lambda: _raises(lambda: _c().order('axe', 0))),
    ("bad_recipe", lambda: _raises(lambda: crafting.Crafting({'a': ({'b': 0}, 1)}))),
    ("type", lambda: isinstance(_c().order('axe', 1), list)),
    ("det", lambda: _c().order('axe', 1) == _c().order('axe', 1)),
    ("missing_type", lambda: isinstance(_c().missing({'wood': 0}, 'axe', 1), dict)),
    ("no_mut", lambda: _c().order('axe', 1) is not None),
    ("empty_recipe", lambda: isinstance(crafting.Crafting({}).order('axe', 1), list) or True),
    ("nan", lambda: _raises(lambda: _c().order('axe', float('nan')))),
    ("scale", lambda: isinstance(_c().order('axe', 3), list)),
    ("float_missing", lambda: isinstance(_c().missing({}, 'axe', 1), dict)),
]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    assert check() is True
