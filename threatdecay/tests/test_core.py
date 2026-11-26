import math

import pytest

import threatdecay

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def _norm(v):
    return math.sqrt(sum(c * c for c in v))

def _t():
    return threatdecay.ThreatDecay(1.0)

CASES = [
    ("empty", lambda: _t().current() is None),
    ("add", lambda: (_t().add('a', 10.0), _t().current())[1] == 'a'),
    ("half", lambda: (_t().add('a', 10.0), _t().tick(1.0), _t().threat('a'))[2] < 10.0),
    ("hysteresis", lambda: (lambda t: (t.add('a', 10.0), t.add('b', 10.5), t.current())[2] == 'a')(_t())),
    ("switch", lambda: (lambda t: (t.add('a', 10.0), t.add('b', 12.0), t.current())[2] == 'b')(_t())),
    ("bad_half", lambda: _raises(lambda: threatdecay.ThreatDecay(0.0))),
    ("bad_amount", lambda: _raises(lambda: _t().add('a', -1.0))),
    ("type", lambda: isinstance(_t().add('a', 1.0), float)),
    ("det", lambda: (lambda t: (t.add('a', 1.0), t.current())[1])(_t()) == (lambda t: (t.add('a', 1.0), t.current())[1])(_t())),
    ("clear", lambda: (lambda t: (t.add('a', 1.0), t.tick(100.0), t.current())[2] is None)(_t())),
    ("nan", lambda: _raises(lambda: _t().tick(float('nan')))),
    ("no_mut", lambda: _t().add('a', 1.0) is not None),
    ("threat_type", lambda: (lambda t: (t.add('a', 1.0), isinstance(t.threat('a'), float))[1])(_t())),
    ("current_type", lambda: (lambda t: (t.add('a', 1.0), isinstance(t.current(), str))[1])(_t())),
    ("two_targets", lambda: (lambda t: (t.add('a', 1.0), t.add('b', 2.0), len(t.all()))[2] == 2)(_t())),
]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    assert check() is True
