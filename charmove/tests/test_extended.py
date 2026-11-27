"""题面硬约束的扩展回归测试。

这些用例只使用标准库/pytest，覆盖 CCD、斜坡、台阶、稳定性、错误分类和性能。
"""

import math
import time

import pytest

import charmove
from charmove import (
    CharMove,
    InvalidDTError,
    InvalidPositionError,
    InvalidTileError,
    InvalidTilesError,
    StepTooHighError,
)


TILES = [[0, 0, 0], [0, 1, 0], [1, 1, 1]]


def test_axis_order_is_x_then_y():
    m = CharMove(TILES)
    assert m.axis_order() == ("x", "y")
    assert charmove.AXIS_ORDER == ("x", "y")


def test_step_and_ccd_are_same_result():
    m1 = CharMove(TILES)
    m2 = CharMove(TILES)
    a = m1.step((0.5, 0.5), (3.0, 2.0), 0.1)
    b = m2.continuous_collision((0.5, 0.5), (3.0, 2.0), 0.1)
    assert a[:2] == b[:2]
    assert abs(a[0] - b[0]) <= 1e-12
    assert abs(a[1] - b[1]) <= 1e-12


def test_fast_movement_does_not_tunnel_through_wall():
    wall = [[0, 0, 0], [0, 1, 0], [0, 0, 0]]
    m = CharMove(wall, auto_step=False, slide_on_slope=False, gravity=0.0)
    r = m.step((0.5, 1.5), (100.0, 0.0), 1.0)
    assert r.blocked_x is True
    assert abs(r[0] - 1.0) <= 1e-9
    assert r[0] < 1.0


def test_wall_contact_is_stable_to_1e_12():
    wall = [[0, 0, 0], [0, 1, 0], [0, 0, 0]]
    m = CharMove(wall, auto_step=False, slide_on_slope=False, gravity=0.0)
    first = m.step((0.5, 1.5), (10.0, 0.0), 0.2)
    second = m.step(first[:2], (10.0, 0.0), 0.2)
    third = m.step(second[:2], (10.0, 0.0), 0.2)
    assert max(abs(second[0] - first[0]), abs(second[1] - first[1])) <= 1e-12
    assert max(abs(third[0] - second[0]), abs(third[1] - second[1])) <= 1e-12


def test_landing_has_no_penetration_beyond_tolerance():
    floor_map = [[0, 0], [1, 1]]
    m = CharMove(floor_map, slide_on_slope=False, gravity=0.0)
    r = m.step((0.5, 0.2), (0.0, 20.0), 1.0)
    assert abs(r[1] - 1.0) <= 1e-9
    assert r.penetration <= 1e-9
    again = m.step(r[:2], (0.0, 20.0), 0.05)
    assert max(abs(again[0] - r[0]), abs(again[1] - r[1])) <= 1e-12


def test_slope_value_normal_and_direction():
    tiles = [[{"type": "slope", "direction": "\\"}]]
    m = CharMove(tiles)
    angle = float(m.slope((0.4, 0.4)))
    assert abs(angle - math.pi / 4.0) <= 1e-9
    nx, ny = m.slope_normal((0.4, 0.4))
    assert abs(nx - math.sqrt(0.5)) <= 1e-9
    assert abs(ny + math.sqrt(0.5)) <= 1e-9


def test_steep_slope_slides_downhill_and_stays_on_surface():
    tiles = [[{"type": "slope", "m": 2.0}]]
    m = CharMove(tiles)
    x0, y0 = 0.2, 0.4
    r = m.step((x0, y0), (0.0, 0.0), 0.01)
    assert r.sliding is True
    assert r[0] > x0 and r[1] > y0
    assert abs(r[1] - 2.0 * r[0]) <= 1e-9
    assert r.penetration <= 1e-9


def test_slope_limit_is_strict():
    forty_five = [[{"type": "slope", "m": 1.0}]]
    steep = [[{"type": "slope", "m": 1.0001}]]
    assert CharMove(forty_five).step((0.2, 0.2), (0, 0), 0.01).sliding is False
    assert CharMove(steep).step((0.2, 0.20002), (0, 0), 0.01).sliding is True


def test_step_height_classification_is_distinguishable():
    m = CharMove([[0]], max_step=0.5)
    assert m.can_climb_step(0.5) is True
    assert m.classify_step(0.25) == "climbed"
    assert m.can_climb_step(0.500000001) is False
    assert m.classify_step(0.75) == "blocked"
    climbed = m.climb_step(0.25)
    blocked = m.climb_step(0.75)
    assert climbed["climbed"] is True and climbed["delta_y"] < 0
    assert blocked["blocked"] is True and blocked["allowed"] is False
    with pytest.raises(StepTooHighError):
        m.climb_step(0.75, raise_on_blocked=True)


def test_map_step_climbs_or_blocks_and_stays_stable():
    tiles = [
        [0, 0, 0],
        [0, {"type": "step", "height": 0.25}, 0],
        [1, 1, 1],
    ]
    m = CharMove(tiles, max_step=0.5)
    r = m.step((0.5, 2.0), (1.0, 0.0), 1.0)
    assert r.climbed is True
    assert r.blocked is False
    assert r[0] >= 1.5 - 1e-12
    assert abs(r[1] - 1.75) <= 1e-9

    tiles[1][1] = {"type": "step", "height": 0.75}
    hard = CharMove(tiles, max_step=0.5)
    r = hard.step((0.5, 2.0), (1.0, 0.0), 1.0)
    again = hard.step(r[:2], (1.0, 0.0), 0.1)
    assert r.climbed is False
    assert r.blocked_x is True
    assert r.reason == "step_too_high"
    assert abs(r[0] - 1.0) <= 1e-9
    assert max(abs(again[0] - r[0]), abs(again[1] - r[1])) <= 1e-12


@pytest.mark.parametrize("bad_dt", [0.0, -0.1, float("nan"), float("inf"), "0.01", True, None])
def test_invalid_dt_type(bad_dt):
    m = CharMove(TILES)
    with pytest.raises(InvalidDTError):
        m.step((0.5, 0.5), (1.0, 0.0), bad_dt)
    with pytest.raises(ValueError):
        m.step((0.5, 0.5), (1.0, 0.0), bad_dt)


@pytest.mark.parametrize("bad_tiles", [[], None, [[]], [[1], [1, 0]], "not-a-map"])
def test_invalid_tile_maps(bad_tiles):
    with pytest.raises(InvalidTilesError):
        CharMove(bad_tiles)
    with pytest.raises(ValueError):
        CharMove(bad_tiles)


def test_invalid_individual_tile_is_tile_error():
    with pytest.raises(InvalidTileError):
        CharMove([[object()]])
    with pytest.raises(InvalidTilesError):
        CharMove([[object()]])


def test_dt_and_tile_errors_are_distinct():
    assert InvalidDTError is not InvalidTilesError
    assert not issubclass(InvalidDTError, InvalidTilesError)
    assert not issubclass(InvalidTilesError, InvalidDTError)
    try:
        CharMove([])
    except InvalidTilesError as exc:
        assert exc.code != "invalid_dt"
    else:
        raise AssertionError("empty map must raise InvalidTilesError")

    try:
        CharMove(TILES).step((0, 0), (1, 0), -1)
    except InvalidDTError as exc:
        assert exc.code == "invalid_dt"
    else:
        raise AssertionError("negative dt must raise InvalidDTError")


def test_invalid_position_and_velocity():
    m = CharMove(TILES)
    with pytest.raises(InvalidPositionError):
        m.step((0.5,), (1, 0), 0.01)
    with pytest.raises(InvalidPositionError):
        m.step((float("nan"), 0.5), (1, 0), 0.01)
    with pytest.raises(charmove.InvalidVelocityError):
        m.step((0.5, 0.5), (float("inf"), 0), 0.01)


def test_deterministic_pair_of_floats():
    m1 = CharMove(TILES)
    m2 = CharMove(TILES)
    a = m1.step((1.5, 1.5), (1.0, 0.0), 0.01)
    b = m2.step((1.5, 1.5), (1.0, 0.0), 0.01)
    assert a == b
    assert len(a) == 2
    assert isinstance(a[0], float) and isinstance(a[1], float)


def test_10k_steps_under_500ms_best_of_three():
    m = CharMove(TILES)

    def run():
        x, y = 0.5, 0.5
        for i in range(10_000):
            r = m.step(
                (x, y),
                (((i % 3) - 1) * 0.9, ((i // 3) % 3 - 1) * 0.7),
                0.016,
            )
            x, y = r[0], r[1]

    run()  # warmup
    elapsed = min(_timed(run) for _ in range(3))
    assert elapsed < 0.5, elapsed


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start
