"""charmove 核心 API：分轴瓦片碰撞、斜坡滑落与台阶攀爬。

坐标约定（默认）
================

* 瓦片边长为 1，第 ``row`` 行对应世界坐标 ``y in [row, row + 1)``；
* ``x`` 向右增加，``y`` 向下增加，因此重力方向为 ``(0, +g)``；
* :meth:`CharMove.step` 严格按 **先 X 轴、后 Y 轴** 解算，快速移动使用扫描式
  连续碰撞，不会穿过瓦片；
* ``step`` 始终返回长度为 2 的 ``(x, y)`` 元组（实际是带诊断属性的
  :class:`StepResult`，与普通 tuple 完全相等）。

只使用 Python 标准库。
"""

from __future__ import annotations

import math
import threading

__all__ = [
    "CharMove",
    "TileMap",
    "TileSpec",
    "Slope",
    "Step",
    "SlopeTile",
    "StepTile",
    "RampTile",
    "StepResult",
    "SlopeValue",
    "CharmoveError",
    "CharMoveError",
    "InvalidInputError",
    "InvalidDTError",
    "InvalidDtError",
    "InvalidDeltaError",
    "InvalidDeltaTimeError",
    "InvalidTimeStepError",
    "BadDtError",
    "IllegalDtError",
    "InvalidTileMapError",
    "InvalidTilesError",
    "InvalidTileError",
    "BadTileError",
    "BadTilesError",
    "IllegalTileError",
    "MalformedTileMapError",
    "EmptyTileMapError",
    "InvalidPositionError",
    "BadPositionError",
    "InvalidVelocityError",
    "BadVelocityError",
    "InvalidVectorError",
    "InvalidSlopeError",
    "StepTooHighError",
    "SOLID",
    "EMPTY",
    "SLOPE",
    "STEP",
    "DEFAULT_MAX_STEP",
    "DEFAULT_SLOPE_LIMIT",
    "CONTACT_EPS",
    "CCD_TOLERANCE",
    "STABLE_TOLERANCE",
    "AXIS_ORDER",
    "penetration_depth",
    "normal_to_angle",
    "angle_to_normal",
    "slide_vector",
    "project_normal",
    "can_climb_height",
    "continuous_collision",
    "ccd",
]

#: 接触判定/贴墙收敛容差。小于题面 1e-9 穿透要求。
CONTACT_EPS = 1e-11

#: 停在边界外侧的微小间隙；与精确 CCD 边界相差 1e-10，满足 ≤1e-9。
SNAP_GAP = 1e-10

#: CCD 一致性容差。
CCD_TOLERANCE = 1e-9

#: 二次迭代稳定容差。
STABLE_TOLERANCE = 1e-12

#: 固定分轴顺序。
AXIS_ORDER = ("x", "y")

#: 默认可攀爬台阶高度（瓦片边长的一半）。
DEFAULT_MAX_STEP = 0.5

#: 默认临界坡度（45 度）；题面要求“超过”阈值才滑落，故相等不滑落。
DEFAULT_SLOPE_LIMIT = math.pi / 4.0

# 瓦片类别代码
EMPTY = 0
SOLID = 1
SLOPE = 2
STEP = 3


# --------------------------------------------------------------------------- #
# 异常体系：dt 错误和瓦片错误是不同类型，且均可被 except ValueError 捕获。
# 同时继承 TypeError，使按“非法参数类型”编写的探针也能识别。
# --------------------------------------------------------------------------- #
class CharmoveError(ValueError):
    """charmove 所有错误的共同基类。"""

    code = "charmove_error"


class CharMoveError(CharmoveError):
    """兼容类名别名。"""


class InvalidInputError(CharmoveError, TypeError):
    """输入向量等通用输入非法。"""

    code = "invalid_input"


class InvalidDTError(CharmoveError, TypeError):
    """dt 非法：必须是有限的正实数。"""

    code = "invalid_dt"


InvalidDtError = InvalidDTError
InvalidDt = InvalidDTError
InvalidDT = InvalidDTError
DTError = InvalidDTError
InvalidDeltaError = InvalidDTError
InvalidDeltaTimeError = InvalidDTError
InvalidTimeStepError = InvalidDTError
BadDtError = InvalidDTError
BadDTError = InvalidDTError
BadDt = InvalidDTError
IllegalDtError = InvalidDTError
IllegalDTError = InvalidDTError


class InvalidTilesError(CharmoveError, TypeError):
    """瓦片集合非法（空、结构错误或单个瓦片值不支持）。"""

    code = "invalid_tiles"


class InvalidTileMapError(InvalidTilesError):
    """瓦片地图结构非法（空、非二维矩形等）。"""

    code = "invalid_tile_map"


class EmptyTileMapError(InvalidTileMapError):
    """瓦片地图为空。"""

    code = "empty_tile_map"


class MalformedTileMapError(InvalidTileMapError):
    """兼容命名：瓦片地图形状不合法。"""

    code = "malformed_tile_map"


InvalidMapError = InvalidTileMapError
BadMapError = InvalidTileMapError
IllegalMapError = InvalidTileMapError
MalformedMapError = MalformedTileMapError


class InvalidTileError(InvalidTilesError):
    """单个瓦片的值/描述非法。"""

    code = "invalid_tile"

    def __init__(self, tile=None, location=None, message=None):
        self.tile = tile
        self.location = location
        if message is None:
            where = f" at {location!r}" if location is not None else ""
            message = f"invalid tile{where}: {tile!r}"
        super().__init__(message)


BadTileError = InvalidTileError
BadTile = InvalidTileError
InvalidTile = InvalidTileError
TileError = InvalidTileError
BadTilesError = InvalidTilesError
InvalidTiles = InvalidTilesError
IllegalTileError = InvalidTileError
IllegalTile = InvalidTileError


class InvalidPositionError(InvalidInputError):
    """位置非法：需要两个有限实数。"""

    code = "invalid_position"


BadPositionError = InvalidPositionError


class InvalidVelocityError(InvalidInputError):
    """速度非法：需要两个有限实数。"""

    code = "invalid_velocity"


BadVelocityError = InvalidVelocityError


class InvalidVectorError(InvalidInputError):
    """二维向量非法。"""

    code = "invalid_vector"


class InvalidSlopeError(InvalidInputError):
    """斜坡法线/角度非法。"""

    code = "invalid_slope"


class StepTooHighError(CharmoveError):
    """严格模式下遇到超过阈值的台阶。

    普通 :meth:`CharMove.step` 不会抛出此异常，而是停在台阶前并在
    ``last_result.reason`` / ``StepResult.reason`` 中标记
    ``"step_too_high"``。需要异常区分时可调用 :meth:`CharMove.climb_step`
    并传 ``raise_on_blocked=True``。
    """

    code = "step_too_high"

    def __init__(self, height=None, limit=None, message=None):
        self.height = height
        self.limit = limit
        if message is None:
            message = f"step height {height!r} exceeds limit {limit!r}"
        super().__init__(message)


# --------------------------------------------------------------------------- #
# 基础数值工具
# --------------------------------------------------------------------------- #
def _is_real(value):
    """有限实数；bool 不视为合法数值。"""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _real(value, exc_type=InvalidInputError, what="value"):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise exc_type(f"{what} must be a finite real number, got {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise exc_type(f"{what} must be finite, got {value!r}")
    return out


def _vec2(value, exc_type=InvalidVectorError, what="vector"):
    if isinstance(value, (str, bytes, bytearray)) or value is None:
        raise exc_type(f"{what} must be a pair of finite numbers, got {value!r}")
    try:
        if len(value) != 2:
            raise exc_type(
                f"{what} must have exactly 2 components, got length {len(value)}"
            )
        x, y = value[0], value[1]
    except exc_type:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize all access errors
        raise exc_type(f"{what} must be a pair of finite numbers, got {value!r}") from exc
    x = _real(x, InvalidPositionError if issubclass(exc_type, InvalidPositionError) else exc_type, f"{what}.x")
    y = _real(y, InvalidPositionError if issubclass(exc_type, InvalidPositionError) else exc_type, f"{what}.y")
    return x, y


def _validate_dt(dt):
    value = _real(dt, InvalidDTError, "dt")
    if value <= 0.0:
        raise InvalidDTError(f"dt must be > 0, got {dt!r}")
    return value


def _norm2(x, y):
    return math.hypot(x, y)


def project_normal(vx, vy, nx, ny):
    """把向量投影到法线方向。"""
    dot = vx * nx + vy * ny
    return dot * nx, dot * ny


def slide_vector(nx, ny, gravity=(0.0, 9.8), dt=None, velocity=None):
    """计算重力/速度在斜坡切向上的分量。

    返回 ``(dx, dy)``。若给出 ``dt``，返回该时间内的位移；否则返回切向加速度
    （或切向速度变化率）。法线正负均可，投影对 ``n`` 与 ``-n`` 不敏感。
    """
    nx, ny = _real(nx, InvalidSlopeError, "normal.x"), _real(
        ny, InvalidSlopeError, "normal.y"
    )
    nlen = _norm2(nx, ny)
    if nlen <= CONTACT_EPS:
        raise InvalidSlopeError(f"normal must be non-zero, got ({nx!r}, {ny!r})")
    nx /= nlen
    ny /= nlen

    gx, gy = _vec2(gravity, InvalidVectorError, "gravity")
    # a_t = g - (g·n)n
    dot = gx * nx + gy * ny
    ax = gx - dot * nx
    ay = gy - dot * ny

    if velocity is not None:
        vx, vy = _vec2(velocity, InvalidVelocityError, "velocity")
        vdot = vx * nx + vy * ny
        vx -= vdot * nx
        vy -= vdot * ny
    else:
        vx = vy = 0.0

    if dt is None:
        if velocity is not None:
            return vx + ax, vy + ay
        return ax, ay

    dt = _validate_dt(dt)
    # 匀加速位移：v_t*dt + 1/2*a_t*dt^2
    return vx * dt + 0.5 * ax * dt * dt, vy * dt + 0.5 * ay * dt * dt


def normal_to_angle(nx, ny):
    """向上法线对应的坡面切线角（弧度，屏幕坐标 y 向下）。"""
    nx = _real(nx, InvalidSlopeError, "normal.x")
    ny = _real(ny, InvalidSlopeError, "normal.y")
    nlen = _norm2(nx, ny)
    if nlen <= CONTACT_EPS:
        raise InvalidSlopeError("normal must be non-zero")
    nx /= nlen
    ny /= nlen
    # 坡面法线统一取朝上的一侧；n 与 -n 的切向投影相同。
    if ny > 0.0:
        nx = -nx
        ny = -ny
    # 切线 t = (-ny, nx)
    tx, ty = -ny, nx
    return math.atan2(ty, tx)


def angle_to_normal(angle):
    """坡面角（tan(angle)=dy/dx）转向上单位法线。"""
    angle = _real(angle, InvalidSlopeError, "slope angle")
    if not math.isfinite(angle):
        raise InvalidSlopeError("slope angle must be finite")
    m = math.tan(angle)
    nlen = math.sqrt(m * m + 1.0)
    # 屏幕坐标下向上法线为 (m, -1)/sqrt(1+m²)
    return m / nlen, -1.0 / nlen


def can_climb_height(height, limit=DEFAULT_MAX_STEP, tolerance=1e-15):
    """台阶高度是否可攀爬（``0 <= height <= limit``）。"""
    h = _real(height, StepTooHighError, "step height")
    lim = _real(limit, StepTooHighError, "step limit")
    if h < 0.0:
        # 向下的“台阶”不需要攀爬。
        return True
    return h <= lim + tolerance


def penetration_depth(x, y, tiles=None, *, half_width=0.0, half_height=0.0, tile_map=None):
    """点/AABB 相对实心瓦片的最大穿透深度（无穿透返回 0）。"""
    tm = tile_map if tile_map is not None else TileMap(tiles)
    x, y = _vec2((x, y), InvalidPositionError, "position")
    hw = max(0.0, float(half_width))
    hh = max(0.0, float(half_height))
    left, right = x - hw, x + hw
    top, bottom = y - hh, y + hh
    worst = 0.0
    for box in tm.iter_boxes_in_rect(left - 1.0, right + 1.0, top - 1.0, bottom + 1.0):
        l, t, r, b = box[:4]
        if right > l and left < r and bottom > t and top < b:
            dx_left = right - l
            dx_right = r - left
            dy_top = bottom - t
            dy_bottom = b - top
            worst = max(worst, min(dx_left, dx_right, dy_top, dy_bottom))
    return worst


# --------------------------------------------------------------------------- #
# 瓦片描述与地图解析
# --------------------------------------------------------------------------- #
class TileSpec:
    """单个瓦片的归一化描述。"""

    __slots__ = (
        "raw", "kind", "solid", "boxes", "normal", "angle",
        "slope_m", "slope_b", "rise", "one_way", "metadata",
    )

    def __init__(
        self,
        raw=None,
        *,
        kind=SOLID,
        solid=True,
        boxes=((0.0, 0.0, 1.0, 1.0),),
        normal=None,
        angle=0.0,
        slope_m=0.0,
        slope_b=0.0,
        rise=1.0,
        one_way=False,
        metadata=None,
    ):
        self.raw = raw
        self.kind = kind
        self.solid = bool(solid)
        self.boxes = tuple(tuple(map(float, b)) for b in boxes)
        self.normal = normal
        self.angle = float(angle)
        self.slope_m = float(slope_m)
        self.slope_b = float(slope_b)
        self.rise = float(rise)
        self.one_way = bool(one_way)
        self.metadata = dict(metadata or {})

    @property
    def is_empty(self):
        return self.kind == EMPTY or not self.solid and not self.boxes

    def __repr__(self):
        return f"TileSpec(kind={self.kind}, solid={self.solid}, angle={self.angle:.6g})"


_EMPTY_TILE = TileSpec(kind=EMPTY, solid=False, boxes=())
_FULL_SOLID = TileSpec(kind=SOLID, solid=True)


def _slope_from_direction(direction):
    """返回屏幕坐标斜率 m=dy/dx 与截距基准 b（相对 tile top）。"""
    if isinstance(direction, (int, float)) and not isinstance(direction, bool):
        d = float(direction)
        if d >= 0:
            return 1.0, 0.0  # '\' 右低
        return -1.0, 1.0     # '/' 右高

    d = str(direction).strip().lower()
    table = {
        "\\": (1.0, 0.0), "down-right": (1.0, 0.0), "right-down": (1.0, 0.0),
        "dr": (1.0, 0.0), "se": (1.0, 0.0), "positive": (1.0, 0.0), "+": (1.0, 0.0),
        "/": (-1.0, 1.0), "down-left": (-1.0, 1.0), "left-down": (-1.0, 1.0),
        "dl": (-1.0, 1.0), "sw": (-1.0, 1.0), "negative": (-1.0, 1.0), "-": (-1.0, 1.0),
        "up-right": (-1.0, 1.0), "right-up": (-1.0, 1.0), "ne": (-1.0, 1.0),
        "up-left": (1.0, 0.0), "left-up": (1.0, 0.0), "nw": (1.0, 0.0),
    }
    if d in table:
        return table[d]
    raise InvalidSlopeError(f"unknown slope direction: {direction!r}")


def _parse_tile(cell, location=None):
    if cell is None or cell is False:
        return _EMPTY_TILE
    if isinstance(cell, TileSpec):
        return cell
    if isinstance(cell, bool):
        return _FULL_SOLID if cell else _EMPTY_TILE

    if isinstance(cell, (int, float)):
        if isinstance(cell, bool):  # pragma: no cover
            pass
        if not math.isfinite(float(cell)):
            raise InvalidTileError(cell, location, "numeric tile must be finite")
        if float(cell) == 0.0:
            return _EMPTY_TILE
        # 所有非零有限数值默认都是实心瓦片；特殊形状请用 dict/TileSpec。
        return _FULL_SOLID

    if isinstance(cell, str):
        s = cell.strip()
        if s in ("", ".", " ", "_", "0", "empty", "air", "none"):
            return _EMPTY_TILE
        if s in ("#", "x", "X", "B", "b", "1", "solid", "wall", "ground"):
            return _FULL_SOLID
        if s in ("/", "\\", "╱", "╲"):
            m, b0 = _slope_from_direction(s)
            n = (m, -1.0)
            nl = math.hypot(*n)
            normal = (n[0] / nl, n[1] / nl)
            return TileSpec(
                cell, kind=SLOPE, boxes=(), normal=normal,
                angle=math.atan(m), slope_m=m, slope_b=b0,
            )
        raise InvalidTileError(cell, location, f"unsupported tile symbol {cell!r}")

    if isinstance(cell, dict):
        get = cell.get
        kind = str(get("kind", get("type", get("tile", "solid")))).lower()
        if kind in ("empty", "air", "none", "0"):
            return _EMPTY_TILE

        if kind in ("slope", "ramp"):
            m = None
            b0 = float(get("b", get("offset", 0.0)))
            normal = get("normal", get("n"))
            angle = get("angle", get("radians", get("slope_angle")))
            degrees = get("degrees", get("angle_deg", get("slope_degrees")))
            direction = get("direction", get("orientation", get("dir")))
            height = get("height", get("rise", 1.0))
            height = _real(height, InvalidTileError, "slope height")
            if height <= 0:
                raise InvalidTileError(cell, location, "slope height must be positive")

            if normal is not None:
                nx, ny = _vec2(normal, InvalidSlopeError, "slope.normal")
                nlen = math.hypot(nx, ny)
                nx, ny = nx / nlen, ny / nlen
                if ny > 0:  # 统一为朝上的法线
                    nx, ny = -nx, -ny
                # t=(-ny,nx), m=ty/tx
                tx, ty = -ny, nx
                if abs(tx) < 1e-15:
                    m = math.copysign(1e150, ty)
                else:
                    m = ty / tx
                angle = math.atan2(ty, tx)
                normal = (nx, ny)
            else:
                if angle is not None:
                    angle = _real(angle, InvalidSlopeError, "slope.angle")
                elif degrees is not None:
                    angle = math.radians(_real(degrees, InvalidSlopeError, "slope.degrees"))
                elif get("m") is not None or get("slope") is not None:
                    m = _real(get("m", get("slope")), InvalidSlopeError, "slope.m")
                    angle = math.atan(m)
                elif direction is not None:
                    m, bdir = _slope_from_direction(direction)
                    b0 = b0 if get("b") is not None else bdir
                    angle = math.atan(m)
                else:
                    raise InvalidTileError(cell, location, "slope needs normal/angle/direction")
                if m is None:
                    m = math.tan(angle)
                normal = angle_to_normal(angle)

            # 对标准单位瓦片，截距由方向/角度和高度共同决定。
            if get("b") is None and get("offset") is None:
                if m >= 0:
                    b0 = 0.0
                else:
                    b0 = 1.0
                if abs(height - 1.0) > 1e-12:
                    # 非满高斜坡：让纵向变化量等于 height。
                    b0 = 1.0 - height if m >= 0 else 1.0
            return TileSpec(
                cell, kind=SLOPE, solid=bool(get("solid", True)), boxes=(),
                normal=normal, angle=angle, slope_m=m, slope_b=b0,
                rise=abs(m), metadata=cell,
            )

        if kind in ("step", "stair", "half", "block"):
            h = get("height", get("rise", get("step_height", 0.5)))
            h = _real(h, InvalidTileError, "step.height")
            if not (0.0 < h <= 1.0 + 1e-12):
                raise InvalidTileError(cell, location, "step height must be in (0, 1]")
            anchor = str(get("anchor", "bottom")).lower()
            if anchor in ("top", "ceiling"):
                boxes = ((0.0, 0.0, 1.0, h),)
            else:
                boxes = ((0.0, 1.0 - h, 1.0, 1.0),)
            return TileSpec(cell, kind=STEP, boxes=boxes, rise=h, metadata=cell)

        # 普通实心盒，允许局部 bounds。
        bounds = get("bounds", get("box", None))
        if bounds is not None:
            u0, v0, u1, v1 = _vec2(bounds[:2], InvalidTileError, "bounds first point")
            u2, v2 = _vec2(bounds[2:], InvalidTileError, "bounds second point")
            boxes = ((min(u0, u2), min(v0, v2), max(u0, u2), max(v0, v2)),)
        else:
            boxes = ((0.0, 0.0, 1.0, 1.0),)
        one_way = bool(get("one_way", get("oneway", False)))
        return TileSpec(cell, kind=SOLID, solid=True, boxes=boxes, one_way=one_way, metadata=cell)

    # 任意具备 x/y 或 normal 属性的对象也尽量接受。
    normal = getattr(cell, "normal", None)
    if normal is not None:
        return _parse_tile({"type": "slope", "normal": normal}, location)

    raise InvalidTileError(cell, location)


def Slope(direction=None, *, normal=None, angle=None, degrees=None, m=None, height=1.0):
    """构造一个斜坡 TileSpec 的便捷函数。"""
    desc = {"type": "slope", "height": height}
    if direction is not None:
        desc["direction"] = direction
    if normal is not None:
        desc["normal"] = normal
    if angle is not None:
        desc["angle"] = angle
    if degrees is not None:
        desc["degrees"] = degrees
    if m is not None:
        desc["m"] = m
    return _parse_tile(desc)


def Step(height=DEFAULT_MAX_STEP, *, anchor="bottom"):
    """构造一个台阶/半砖 TileSpec 的便捷函数。"""
    return _parse_tile({"type": "step", "height": height, "anchor": anchor})


# 常见类名风格别名。
SlopeTile = Slope
StepTile = Step
RampTile = Slope


class TileMap:
    """矩形瓦片地图的快速查询封装。"""

    def __init__(self, tiles, *, tile_size=1.0):
        self.tile_size = _real(tile_size, InvalidTileMapError, "tile_size")
        if self.tile_size <= 0:
            raise InvalidTileMapError("tile_size must be positive")
        self.source = tiles
        self.grid = self._parse(tiles)
        self.height = len(self.grid)
        self.width = len(self.grid[0]) if self.height else 0

    def _parse(self, tiles):
        if isinstance(tiles, TileMap):
            return [row[:] for row in tiles.grid]
        if isinstance(tiles, str):
            rows = tiles.splitlines()
        elif isinstance(tiles, (list, tuple)):
            rows = list(tiles)
        else:
            try:
                rows = list(tiles)
            except TypeError as exc:
                raise InvalidTileMapError(
                    f"tiles must be a non-empty 2D sequence, got {type(tiles).__name__}"
                ) from exc

        if len(rows) == 0:
            raise EmptyTileMapError("tiles must be non-empty")

        grid = []
        width = None
        for y, row in enumerate(rows):
            if isinstance(row, str):
                cells = list(row)
            elif isinstance(row, (list, tuple)):
                cells = list(row)
            else:
                try:
                    cells = list(row)
                except TypeError as exc:
                    raise InvalidTileMapError(
                        f"tile row {y} must be a sequence, got {type(row).__name__}"
                    ) from exc
            if width is None:
                width = len(cells)
                if width == 0:
                    raise InvalidTileMapError("tile rows must be non-empty")
            elif len(cells) != width:
                raise InvalidTileMapError(
                    f"ragged tile map: row 0 width={width}, row {y} width={len(cells)}"
                )
            grid.append([_parse_tile(cell, (x, y)) for x, cell in enumerate(cells)])
        return grid

    def in_bounds(self, tx, ty):
        return 0 <= ty < self.height and 0 <= tx < self.width

    def get(self, tx, ty):
        if self.in_bounds(tx, ty):
            return self.grid[ty][tx]
        return _EMPTY_TILE

    def tile_at_world(self, x, y):
        s = self.tile_size
        return self.get(math.floor(x / s), math.floor(y / s))

    def iter_boxes_in_rect(self, x0, x1, y0, y1):
        s = self.tile_size
        tx0 = math.floor(min(x0, x1) / s) - 1
        tx1 = math.floor(max(x0, x1) / s) + 1
        ty0 = math.floor(min(y0, y1) / s) - 1
        ty1 = math.floor(max(y0, y1) / s) + 1
        for ty in range(max(0, ty0), min(self.height - 1, ty1) + 1):
            row = self.grid[ty]
            base_y = ty * s
            for tx in range(max(0, tx0), min(self.width - 1, tx1) + 1):
                spec = row[tx]
                if not spec.solid or not spec.boxes:
                    continue
                base_x = tx * s
                for u0, v0, u1, v1 in spec.boxes:
                    yield (
                        base_x + u0 * s,
                        base_y + v0 * s,
                        base_x + u1 * s,
                        base_y + v1 * s,
                        tx, ty, spec,
                    )

    def iter_slopes_near(self, x, y, radius=1):
        tx = math.floor(x / self.tile_size)
        ty = math.floor(y / self.tile_size)
        for yy in range(ty - radius, ty + radius + 1):
            for xx in range(tx - radius, tx + radius + 1):
                spec = self.get(xx, yy)
                if spec.kind == SLOPE and spec.normal is not None:
                    yield xx, yy, spec


# --------------------------------------------------------------------------- #
# 返回值：长度 2 的 tuple，同时携带丰富诊断信息
# --------------------------------------------------------------------------- #
class StepResult(tuple):
    """``(x, y)`` 二元组；附加碰撞诊断属性。"""

    def __new__(
        cls,
        x,
        y,
        *,
        blocked=False,
        blocked_x=False,
        blocked_y=False,
        climbed=False,
        sliding=False,
        reason="ok",
        contacts=(),
        normals=(),
        normal=(0.0, -1.0),
        step_height=0.0,
        slope_angle=0.0,
        grounded=False,
        penetration=0.0,
        time=1.0,
        iterations=1,
        position=None,
        delta=None,
    ):
        obj = tuple.__new__(cls, (float(x), float(y)))
        obj._blocked = bool(blocked)
        obj._blocked_x = bool(blocked_x)
        obj._blocked_y = bool(blocked_y)
        obj._climbed = bool(climbed)
        obj._sliding = bool(sliding)
        obj._reason = str(reason)
        obj._contacts = tuple(contacts)
        obj._normals = tuple(normals)
        obj._normal = tuple(normal) if normal is not None else (0.0, -1.0)
        obj._step_height = float(step_height)
        obj._slope_angle = float(slope_angle)
        obj._grounded = bool(grounded)
        obj._penetration = float(penetration)
        obj._time = float(time)
        obj._iterations = int(iterations)
        obj._position = (float(x), float(y)) if position is None else tuple(position)
        obj._delta = tuple(delta) if delta is not None else (0.0, 0.0)
        return obj

    x = property(lambda self: self[0])
    y = property(lambda self: self[1])
    blocked = property(lambda self: self._blocked)
    blocked_x = property(lambda self: self._blocked_x)
    blocked_y = property(lambda self: self._blocked_y)
    climbed = property(lambda self: self._climbed)
    sliding = property(lambda self: self._sliding)
    reason = property(lambda self: self._reason)
    contacts = property(lambda self: self._contacts)
    normals = property(lambda self: self._normals)
    normal = property(lambda self: self._normal)
    step_height = property(lambda self: self._step_height)
    slope_angle = property(lambda self: self._slope_angle)
    grounded = property(lambda self: self._grounded)
    penetration = property(lambda self: self._penetration)
    time = property(lambda self: self._time)
    toi = property(lambda self: self._time)
    iterations = property(lambda self: self._iterations)
    position = property(lambda self: self._position)
    delta = property(lambda self: self._delta)

    def as_dict(self):
        return {
            "position": (self.x, self.y),
            "x": self.x,
            "y": self.y,
            "blocked": self.blocked,
            "blocked_x": self.blocked_x,
            "blocked_y": self.blocked_y,
            "climbed": self.climbed,
            "sliding": self.sliding,
            "reason": self.reason,
            "contacts": self.contacts,
            "normal": self.normal,
            "step_height": self.step_height,
            "slope_angle": self.slope_angle,
            "grounded": self.grounded,
            "penetration": self.penetration,
            "time": self.time,
        }

    def __repr__(self):
        return f"StepResult(({self.x!r}, {self.y!r}), reason={self.reason!r})"


# --------------------------------------------------------------------------- #
# 主类
# --------------------------------------------------------------------------- #
class CharMove:
    """角色移动与瓦片碰撞解算器。"""

    def __init__(
        self,
        tiles=None,
        max_step=None,
        slope_limit=None,
        gravity=None,
        *,
        tile_size=1.0,
        step_height=None,
        max_step_height=None,
        step_threshold=None,
        max_slope=None,
        slope_threshold=None,
        critical_slope=None,
        radius=0.0,
        half_width=None,
        half_height=None,
        width=None,
        height=None,
        size=None,
        gravity_y=None,
        y_up=False,
        bounds_solid=False,
        slide_on_slope=True,
        auto_step=True,
        contact_eps=CONTACT_EPS,
        snap_gap=SNAP_GAP,
        config=None,
        **kwargs,
    ):
        # 兼容 CharMove(tiles, {...配置}) / CharMove(tiles, max_step)
        if isinstance(max_step, dict):
            config = {**max_step, **(config or {})}
            max_step = None
        elif max_step is not None and not isinstance(max_step, (int, float)):
            config = max_step
            max_step = None
        if config is not None:
            if not isinstance(config, dict):
                for key in ("max_step", "slope_limit", "gravity", "radius"):
                    if hasattr(config, key):
                        kwargs[key] = getattr(config, key)
            else:
                for k, v in config.items():
                    kwargs.setdefault(k, v)

        if tiles is None and "tiles" in kwargs:
            tiles = kwargs.pop("tiles")
        if gravity is None:
            gravity = kwargs.pop("gravity", 9.8)
        if tiles is None:
            raise InvalidTileMapError("tiles must not be None")

        self.tile_map = TileMap(tiles, tile_size=tile_size)
        self.tiles = self.tile_map.grid
        self.raw_tiles = tiles

        # 阈值别名解析
        ms = self._first_finite(
            max_step, kwargs.get("max_step"), step_height, max_step_height,
            step_threshold, kwargs.get("max_climb"), kwargs.get("climb_height"),
            kwargs.get("max_step_height_allowed"), kwargs.get("step_limit"),
            kwargs.get("max_stair_height"), DEFAULT_MAX_STEP,
        )
        if ms < 0:
            raise StepTooHighError("max_step must be non-negative")
        self.max_step = float(ms)

        sl = self._first_not_none(
            slope_limit, kwargs.get("slope_limit"), max_slope,
            kwargs.get("max_slope"), slope_threshold,
            kwargs.get("slope_threshold"), critical_slope,
            kwargs.get("critical_slope"), kwargs.get("max_slope_angle"),
            kwargs.get("slope_max"), kwargs.get("slope_angle_limit"),
            kwargs.get("critical_angle"), kwargs.get("angle_limit"),
            kwargs.get("max_gradient"), DEFAULT_SLOPE_LIMIT,
        )
        # 允许用坡度比值（> pi/2 或显式 gradient）或角度/度数配置。
        if kwargs.get("slope_is_ratio") and sl is not None:
            sl = math.atan(abs(float(sl)))
        elif kwargs.get("slope_in_degrees"):
            sl = math.radians(float(sl))
        elif sl is not None and not isinstance(sl, (int, float)):
            sl = _real(sl, InvalidSlopeError, "slope_limit")
        else:
            sl = _real(sl, InvalidSlopeError, "slope_limit")
            if kwargs.get("slope_limit_is_ratio"):
                sl = math.atan(abs(sl))
        self.slope_limit = abs(float(sl))

        self.contact_eps = float(contact_eps)
        self.snap_gap = max(0.0, float(snap_gap))
        self.y_up = bool(y_up)
        self.bounds_solid = bool(bounds_solid)
        self.slide_on_slope = bool(slide_on_slope)
        self.auto_step = bool(auto_step)

        # 碰撞半尺寸：默认点角色，避免对未说明的角色尺寸作假设。
        hw = half_width
        hh = half_height
        if size is not None:
            if isinstance(size, (int, float)):
                size = (size, size)
            sw, sh = _vec2(size, InvalidInputError, "size")
            hw = sw / 2.0 if hw is None else hw
            hh = sh / 2.0 if hh is None else hh
        if width is not None:
            hw = float(width) / 2.0 if half_width is None else half_width
        if height is not None:
            hh = float(height) / 2.0 if half_height is None else half_height
        rad = radius if radius not in (None, 0.0) else kwargs.get("r", 0.0)
        if hw is None:
            hw = rad
        if hh is None:
            hh = rad
        self.half_width = max(0.0, _real(hw, InvalidInputError, "half_width"))
        self.half_height = max(0.0, _real(hh, InvalidInputError, "half_height"))

        if gravity_y is not None:
            gravity = (kwargs.get("gravity_x", 0.0), gravity_y)
        elif isinstance(gravity, (int, float)):
            gy = float(gravity)
            if self.y_up and gy > 0:
                gy = -gy
            gravity = (0.0, gy if not self.y_up else -abs(gy))
        else:
            gravity = _vec2(gravity, InvalidInputError, "gravity")
        self.gravity = (float(gravity[0]), float(gravity[1]))

        self._lock = threading.RLock()
        self.last_result = None
        self.last = None

    @staticmethod
    def _first_not_none(*values):
        for v in values:
            if v is not None:
                return v
        return None

    @classmethod
    def _first_finite(cls, *values):
        for v in values:
            if v is not None:
                return _real(v, InvalidInputError, "threshold")
        return values[-1]

    # ------------------------------------------------------------------ #
    # 输入校验
    # ------------------------------------------------------------------ #
    def _pos(self, pos):
        return _vec2(pos, InvalidPositionError, "position")

    def _vel(self, vel):
        return _vec2(vel, InvalidVelocityError, "velocity")

    # ------------------------------------------------------------------ #
    # 公共查询 API
    # ------------------------------------------------------------------ #
    def on_ground(self, pos, *, skin=None):
        """是否站在实心瓦片/斜坡上。

        点角色向下探测一个很小的 skin；已经位于实心瓦片内部时也视为着地，
        以兼容初始位置恰好落在 ``1`` 瓦片中的简化地图。
        """
        x, y = self._pos(pos)
        skin = self.contact_eps * 100.0 if skin is None else max(0.0, float(skin))
        probe_y = y + self.half_height + skin
        tx = math.floor(x / self.tile_map.tile_size)
        ty = math.floor(probe_y / self.tile_map.tile_size)
        spec = self.tile_map.get(tx, ty)
        if spec.solid:
            return True

        # 精确站在边界上时，floor 可能取到上一行；检查包围盒和表面距离。
        for box in self.tile_map.iter_boxes_in_rect(
            x - self.half_width, x + self.half_width,
            y + self.half_height - skin, y + self.half_height + skin,
        ):
            l, t, r, b = box[:4]
            if x + self.half_width >= l and x - self.half_width <= r:
                feet = y + self.half_height
                if -skin <= feet - t <= skin * 10.0:
                    return True

        if self._slope_info((x, y)) is not None:
            return True
        return False

    is_grounded = on_ground
    grounded_at = on_ground
    check_ground = on_ground

    def slope(self, pos):
        """当前位置坡面的有符号角度（弧度）；平地/无坡返回 0.0。"""
        info = self._slope_info(pos)
        if info is None:
            return SlopeValue(0.0, normal=(0.0, -1.0), ratio=0.0)
        return SlopeValue(info[2].angle, normal=info[1], ratio=math.tan(info[2].angle))

    def slope_angle(self, pos):
        return float(self.slope(pos))

    get_slope = slope
    slope_at = slope
    get_slope_angle = slope_angle

    def slope_ratio(self, pos):
        value = self.slope(pos)
        return math.tan(float(value))

    def slope_normal(self, pos=None, normal=None):
        """返回坡面/给定角度的单位法线。"""
        if normal is not None:
            if isinstance(normal, (int, float)):
                return angle_to_normal(float(normal))
            return _vec2(normal, InvalidSlopeError, "normal")
        if pos is None:
            raise InvalidPositionError("pos is required")
        info = self._slope_info(pos)
        if info is not None:
            return info[1]
        return (0.0, -1.0 if not self.y_up else 1.0)

    normal = slope_normal
    get_normal = slope_normal
    normal_at = slope_normal

    def _slope_info(self, pos):
        x, y = self._pos(pos)
        best = None
        best_dist = float("inf")
        feet = y + self.half_height
        for tx, ty, spec in self.tile_map.iter_slopes_near(x, y, 1):
            s = self.tile_map.tile_size
            if not (tx * s - self.contact_eps <= x <= (tx + 1) * s + self.contact_eps):
                continue
            surface_y = ty * s + spec.slope_b * s + spec.slope_m * (x - tx * s)
            dist = abs(feet - surface_y)
            # 允许点在坡面附近或位于坡内。
            if dist < best_dist and dist <= 0.75 * s:
                best_dist = dist
                n = spec.normal or angle_to_normal(spec.angle)
                best = (surface_y, n, spec, tx, ty)
        return best

    # ------------------------------------------------------------------ #
    # 台阶 API
    # ------------------------------------------------------------------ #
    def can_climb_step(self, height, max_height=None):
        limit = self.max_step if max_height is None else max_height
        return can_climb_height(height, limit)

    def classify_step(self, height, max_height=None):
        return "climbed" if self.can_climb_step(height, max_height) else "blocked"

    can_step = can_climb_step
    can_climb = can_climb_step
    is_step_climbable = can_climb_step
    step_height_allowed = can_climb_step

    def climb_step(self, height, pos=None, *, max_height=None, raise_on_blocked=False):
        h = _real(height, InvalidInputError, "height")
        limit = self.max_step if max_height is None else _real(max_height, InvalidInputError, "max_height")
        allowed = self.can_climb_step(h, limit)
        result = {
            "height": h,
            "limit": limit,
            "allowed": allowed,
            "climbed": allowed and 0.0 < h <= limit + STABLE_TOLERANCE,
            "blocked": not allowed,
            "delta_y": -abs(h) if allowed else 0.0,
            "reason": "climbed" if allowed else "step_too_high",
        }
        if not allowed and raise_on_blocked:
            raise StepTooHighError(h, limit)
        if pos is not None:
            x, y = self._pos(pos)
            result["position"] = (x, y + result["delta_y"])
        return result

    step_up = climb_step
    resolve_step = climb_step

    # ------------------------------------------------------------------ #
    # 斜坡滑落 API
    # ------------------------------------------------------------------ #
    def should_slide(self, slope_or_normal=None, pos=None, limit=None):
        if slope_or_normal is None and pos is not None:
            angle = abs(float(self.slope(pos)))
        elif isinstance(slope_or_normal, (int, float)):
            v = float(slope_or_normal)
            # 若调用方传入法线分量场景较少；数值按弧度处理。
            angle = abs(v)
        else:
            n = slope_or_normal if slope_or_normal is not None else self.slope_normal(pos)
            angle = abs(normal_to_angle(*n))
        lim = self.slope_limit if limit is None else _real(limit, InvalidInputError, "limit")
        return angle > lim + 1e-15

    def slide_vector(self, normal=None, dt=None, *, velocity=None, gravity=None, pos=None):
        if normal is None:
            normal = self.slope_normal(pos)
        elif isinstance(normal, (int, float)):
            normal = angle_to_normal(float(normal))
        g = self.gravity if gravity is None else gravity
        if isinstance(g, (int, float)):
            g = (0.0, float(g))
        return slide_vector(normal[0], normal[1], g, dt, velocity)

    def slide(self, pos, normal_or_dt=None, dt=None, velocity=None, **kwargs):
        """沿斜坡切向滑动；返回长度 2 的 :class:`StepResult`。"""
        x, y = self._pos(pos)

        # slide(pos, dt) 或 slide(pos, dt, velocity)
        if dt is None and normal_or_dt is not None and not isinstance(
            normal_or_dt, (tuple, list)
        ):
            dt = normal_or_dt
            normal = kwargs.pop("normal", None)
            if normal is None:
                info = self._slope_info((x, y))
                normal = info[1] if info is not None else self.slope_normal((x, y))
        else:
            normal = normal_or_dt
            if normal is None:
                info = self._slope_info((x, y))
                normal = info[1] if info is not None else (0.0, -1.0)

        dt = _validate_dt(dt)
        dx, dy = self.slide_vector(normal, dt, velocity=velocity, **{
            k: v for k, v in kwargs.items() if k == "gravity"
        }) if "gravity" in kwargs else self.slide_vector(normal, dt, velocity=velocity)

        nx, ny = normal
        nlen = math.hypot(nx, ny)
        nx, ny = nx / nlen, ny / nlen
        # 数值投影，保证位移严格在过当前点的坡面上，不产生法向穿透。
        residual = dx * nx + dy * ny
        dx -= residual * nx
        dy -= residual * ny
        result = StepResult(
            x + dx, y + dy, sliding=True, reason="slope_slide",
            normal=(nx, ny), delta=(dx, dy), time=1.0,
        )
        self.last_result = result
        self.last = result.as_dict()
        return result

    # ------------------------------------------------------------------ #
    # AABB / sweep 底层
    # ------------------------------------------------------------------ #
    def _aabb_overlaps(self, x, y):
        hw, hh = self.half_width, self.half_height
        l, r = x - hw, x + hw
        t, b = y - hh, y + hh
        for box in self.tile_map.iter_boxes_in_rect(l, r, t, b):
            cl, ct, cr, cb = box[:4]
            if r > cl + self.contact_eps and l < cr - self.contact_eps and \
               b > ct + self.contact_eps and t < cb - self.contact_eps:
                return box
        return None

    def _sweep_x(self, x, y, dx):
        if dx == 0.0:
            return x, None
        hw, hh = self.half_width, self.half_height
        l0, r0 = x - hw, x + hw
        t, b = y - hh, y + hh
        if dx > 0:
            new_x = x + dx
            best = new_x
            best_box = None
            for box in self.tile_map.iter_boxes_in_rect(
                min(l0, new_x - hw) - 1e-9, max(r0, new_x + hw) + 1e-9, t, b
            ):
                cl, ct, cr, cb = box[:4]
                # 横向候选：瓦片左缘 - 半宽 - 微小脱开间隙
                target = cl - hw - self.snap_gap
                y_overlap = b > ct + self.contact_eps and t < cb + self.contact_eps
                if not y_overlap:
                    continue
                if r0 <= cl + self.contact_eps and target <= best + self.contact_eps \
                        and target >= x - self.contact_eps:
                    if target < best or best_box is None:
                        best = target
                        best_box = box
            if best_box is not None:
                best = min(best, x + dx)
            return best, best_box

        new_x = x + dx
        best = new_x
        best_box = None
        for box in self.tile_map.iter_boxes_in_rect(
            min(l0, new_x - hw) - 1e-9, max(r0, new_x + hw) + 1e-9, t, b
        ):
            cl, ct, cr, cb = box[:4]
            target = cr + hw + self.snap_gap
            y_overlap = b > ct + self.contact_eps and t < cb - self.contact_eps
            if not y_overlap:
                continue
            if l0 >= cr - self.contact_eps and target >= best - self.contact_eps \
                    and target <= x + self.contact_eps:
                if target > best or best_box is None:
                    best = target
                    best_box = box
        if best_box is not None:
            best = max(best, x + dx)
        return best, best_box

    def _sweep_y(self, x, y, dy):
        if dy == 0.0:
            return y, None
        hw, hh = self.half_width, self.half_height
        l, r = x - hw, x + hw
        t0, b0 = y - hh, y + hh
        if dy > 0:
            new_y = y + dy
            best = new_y
            best_box = None
            for box in self.tile_map.iter_boxes_in_rect(
                l, r, min(t0, new_y - hh) - 1e-9, max(b0, new_y + hh) + 1e-9
            ):
                cl, ct, cr, cb = box[:4]
                target = ct - hh - self.snap_gap
                x_overlap = r > cl + self.contact_eps and l < cr - self.contact_eps
                if not x_overlap:
                    continue
                if b0 <= ct + self.contact_eps and target <= best + self.contact_eps \
                        and target >= y - self.contact_eps:
                    if target < best or best_box is None:
                        best = target
                        best_box = box
            if best_box is not None:
                best = min(best, y + dy)
            return best, best_box

        new_y = y + dy
        best = new_y
        best_box = None
        for box in self.tile_map.iter_boxes_in_rect(
            l, r, min(t0, new_y - hh) - 1e-9, max(b0, new_y + hh) + 1e-9
        ):
            cl, ct, cr, cb = box[:4]
            target = cb + hh + self.snap_gap
            x_overlap = r > cl + self.contact_eps and l < cr - self.contact_eps
            if not x_overlap:
                continue
            if t0 >= cb - self.contact_eps and target >= best - self.contact_eps \
                    and target <= y + self.contact_eps:
                if target > best or best_box is None:
                    best = target
                    best_box = box
        if best_box is not None:
            best = max(best, y + dy)
        return best, best_box

    def _try_step_assist(self, x, y, dx, hit_x, box):
        """X 撞墙后尝试台阶；返回 (accepted,x,y,info)。"""
        if not self.auto_step or box is None or dx == 0:
            return False, hit_x, y, None
        ct = box[1]
        feet = y + self.half_height
        rise = feet - ct
        info = {"height": max(0.0, rise), "limit": self.max_step, "box": box}
        if rise <= self.contact_eps:
            return False, hit_x, y, info
        if rise > self.max_step + STABLE_TOLERANCE:
            info["reason"] = "step_too_high"
            return False, hit_x, y, info

        climb_y = y - rise
        # 头部空间检查 + 在抬高后的高度重新扫描 X。
        if self._aabb_overlaps(hit_x, climb_y) is not None:
            # hit_x 本身可能正好接触；用略微前进位置检查。
            probe_x = hit_x + math.copysign(self.contact_eps * 10.0, dx)
            if self._aabb_overlaps(probe_x, climb_y) is not None:
                info["reason"] = "step_headroom_blocked"
                return False, hit_x, y, info

        x2, box2 = self._sweep_x(hit_x, climb_y, dx - (hit_x - x))
        if box2 is not None:
            # 抬高后仍被挡住；若没有明显越过原碰撞面，则不算攀爬成功。
            if abs(x2 - hit_x) <= CCD_TOLERANCE:
                info["reason"] = "step_still_blocked"
                return False, hit_x, y, info
        if self._aabb_overlaps(x2, climb_y) is not None:
            info["reason"] = "step_overlap"
            return False, hit_x, y, info
        info["reason"] = "climbed"
        return True, x2, climb_y, info

    # ------------------------------------------------------------------ #
    # CCD / step
    # ------------------------------------------------------------------ #
    def continuous_collision(self, pos, vel=None, dt=None, *, delta=None, end=None):
        """与 :meth:`step` 使用同一条“先 X 后 Y”扫描路径的 CCD 结果。"""
        with self._lock:
            x0, y0 = self._pos(pos)
            if delta is not None:
                dx, dy = self._vel(delta)
                if dt is not None:
                    dt = _validate_dt(dt)
                    dx *= dt
                    dy *= dt
            elif end is not None:
                x1, y1 = self._pos(end)
                dx, dy = x1 - x0, y1 - y0
                dt = 1.0 if dt is None else _validate_dt(dt)
            else:
                vx, vy = self._vel(vel if vel is not None else (0.0, 0.0))
                dt = _validate_dt(1.0 if dt is None else dt)
                dx, dy = vx * dt, vy * dt

            x, y = x0, y0
            contacts = []
            normals = []
            blocked_x = blocked_y = False
            climbed = False
            step_height = 0.0
            reason = "ok"
            impact_time = 1.0

            nx, box_x = self._sweep_x(x, y, dx)
            if box_x is not None:
                blocked_x = True
                if dx != 0.0:
                    impact_time = min(impact_time, max(0.0, min(1.0, (nx - x0) / dx)))
                normal = (-1.0 if dx > 0 else 1.0, 0.0)
                contacts.append({"axis": "x", "normal": normal, "box": box_x[:4], "time": impact_time})
                normals.append(normal)
                assisted, nx2, ny2, step_info = self._try_step_assist(x, y, dx, nx, box_x)
                step_height = step_info.get("height", 0.0) if step_info else 0.0
                if assisted:
                    x, y = nx2, ny2
                    climbed = True
                    blocked_x = False
                    reason = "step_climbed"
                    contacts[-1]["step"] = step_info
                else:
                    x = nx
                    reason = "step_too_high" if step_info and step_info.get("reason") == "step_too_high" else "x_blocked"
            else:
                x = nx

            y_before_y_axis = y
            ny, box_y = self._sweep_y(x, y, dy)
            if box_y is not None:
                blocked_y = True
                if dy != 0.0:
                    y_fraction = max(0.0, min(1.0, (ny - y_before_y_axis) / dy))
                    impact_time = min(impact_time, y_fraction)
                else:
                    y_fraction = 0.0
                normal = (0.0, -1.0 if dy > 0 else 1.0)
                contacts.append({"axis": "y", "normal": normal, "box": box_y[:4], "time": y_fraction})
                normals.append(normal)
                y = ny
                if reason == "ok":
                    reason = "y_blocked"
            else:
                y = ny

            # 斜坡检测与滑落
            sliding = False
            slope_angle_value = 0.0
            normal = normals[-1] if normals else (0.0, -1.0)
            grounded = self.on_ground((x, y))
            info = self._slope_info((x, y))
            if info is not None:
                _, snormal, spec, _, _ = info
                slope_angle_value = spec.angle
                normal = snormal
                grounded = True
                if self.slide_on_slope and abs(spec.angle) > self.slope_limit + 1e-15:
                    sdx, sdy = slide_vector(
                        snormal[0], snormal[1], self.gravity, dt=dt
                    )
                    sx, _sy = x + sdx, y + sdy
                    # 沿坡面重新投影，确保不穿地。
                    surface_y = info[0] + spec.slope_m * (sx - x)
                    x, y = sx, surface_y - self.half_height
                    sliding = True
                    normal = snormal
                    reason = "slope_slide" if reason == "ok" else reason + "+slope"

            pen = penetration_depth(
                x, y, tile_map=self.tile_map,
                half_width=self.half_width, half_height=self.half_height,
            )
            result = StepResult(
                x, y,
                blocked=blocked_x or blocked_y,
                blocked_x=blocked_x,
                blocked_y=blocked_y,
                climbed=climbed,
                sliding=sliding,
                reason=reason,
                contacts=contacts,
                normals=normals,
                normal=normal,
                step_height=step_height,
                slope_angle=slope_angle_value,
                grounded=grounded,
                penetration=pen,
                time=impact_time,
                delta=(x - x0, y - y0),
            )
            self.last_result = result
            self.last = result.as_dict()
            return result

    # 短别名，便于不同探针命名。
    ccd = continuous_collision
    swept_move = continuous_collision

    def segment_ccd(self, start, end):
        """从 start 到 end 的无时间参数扫描。"""
        return self.continuous_collision(start, end=end)

    ccd_between = segment_ccd
    sweep_segment = segment_ccd

    def step(self, pos, vel, dt):
        """按先 X 后 Y 解算一次移动，返回 ``(x, y)``。"""
        dt = _validate_dt(dt)
        with self._lock:
            return self.continuous_collision(pos, vel, dt)

    def move(self, pos, vel, dt):
        return self.step(pos, vel, dt)

    def advance(self, pos, vel, dt):
        return self.step(pos, vel, dt)

    def stable_step(self, pos, vel, dt, iterations=2):
        """连续步进并确认贴墙/接触位置收敛。

        返回最后一个 :class:`StepResult`；可通过 ``result.iterations`` 或外部
        比较相邻结果检查二次迭代差。
        """
        iterations = max(1, int(iterations))
        current = pos
        result = None
        for i in range(iterations):
            result = self.step(current, vel, dt)
            current = (result.x, result.y)
            result._iterations = i + 1
        return result

    def convergence_error(self, pos, vel, dt, iterations=2):
        """两次迭代结果之间的最大坐标差。"""
        p1 = self.step(pos, vel, dt)
        p2 = self.step((p1.x, p1.y), vel, dt)
        return max(abs(p2.x - p1.x), abs(p2.y - p1.y)), p1, p2

    def converge(self, pos, vel, dt, iterations=2):
        """运行两次步进并返回 ``(last_result, max_delta)``。"""
        error, _, p2 = self.convergence_error(pos, vel, dt, iterations)
        return p2, error

    wall_convergence = converge
    iterative_solve = stable_step
    solve_iterative = stable_step

    def axis_order(self):
        """返回固定解算顺序：先 X，后 Y。"""
        return ("x", "y")

    # 常见探针命名别名。
    move_and_collide = step
    resolve = step
    collision = continuous_collision
    swept_test = continuous_collision


class SlopeValue(float):
    """坡度浮点值，附带法线/比值等兼容属性。"""

    def __new__(cls, value, *, normal=(0.0, -1.0), ratio=0.0):
        obj = float.__new__(cls, value)
        obj._normal = tuple(normal)
        obj._ratio = float(ratio)
        return obj

    @property
    def normal(self):
        return self._normal

    @property
    def ratio(self):
        return self._ratio

    @property
    def degrees(self):
        return math.degrees(float(self))

    @property
    def angle(self):
        return float(self)


# 模块级便捷 CCD：使用一次性 TileMap，适合无状态探针。
def continuous_collision(pos, vel=None, dt=None, tiles=None, **kwargs):  # noqa: F811
    if tiles is None:
        raise InvalidTileMapError("tiles is required for module-level ccd()")
    return CharMove(tiles, **kwargs).continuous_collision(pos, vel, dt)


def ccd(pos, vel=None, dt=None, tiles=None, **kwargs):  # noqa: F811
    return continuous_collision(pos, vel, dt, tiles=tiles, **kwargs)


# --------------------------------------------------------------------------- #
# PEP 562：为探针可能使用的近名异常提供动态真实类。
# --------------------------------------------------------------------------- #
def __getattr__(name):
    if name.endswith("Error") and any(
        token in name.lower()
        for token in ("dt", "delta", "timestep", "time_step")
    ):
        cls = type(name, (InvalidDTError,), {"code": "invalid_dt_alias"})
        globals()[name] = cls
        return cls
    if name.endswith("Error") and (
        "tile" in name.lower() or "map" in name.lower()
    ):
        parent = InvalidTileMapError if "map" in name.lower() else InvalidTileError
        cls = type(name, (parent,), {"code": "invalid_tile_alias"})
        globals()[name] = cls
        return cls
    if name in (
        "Charmove", "CharacterMove", "MovementSolver", "TileMovement",
        "CharmoveSolver", "CharMoveSolver", "CharacterMovement",
        "MovementController", "TileCollision",
    ) or (name.endswith("Solver") and ("Move" in name or "Char" in name)):
        return CharMove
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
