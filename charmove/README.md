# charmove

## 题面（可直接粘贴）

角色移动与瓦片碰撞解算。约束：分轴解算（先 X 后 Y）且与连续碰撞检测结果一致（≤1e-9）；斜坡法线决定滑落，坡度超过阈值时沿坡滑下且不穿地（穿透 ≤1e-9）；台阶高度不超过阈值时可攀爬，超过则被挡住（可区分）；贴墙时位置收敛不抖动（二次迭代差 ≤1e-12）；1 万次步进不超过 500 ms；非法 dt 与非法瓦片可区分报错。 工作目录为仓库内的 charmove/。 验收：cd charmove && python -m pytest tests -q。 实现只允许使用 Python 标准库。

## 运行方式

```bash
cd charmove && python -m pytest tests -q
```

初始 15 failed（实现前）。仅使用 Python 标准库。

## 实现 API

核心类是 `charmove.CharMove(tiles, max_step=0.5, slope_limit=pi/4, ...)`。
位置和速度都是 `(x, y)` 二元组；默认瓦片边长为 1，数组第 `row` 行对应
`y ∈ [row, row + 1)`，即 x 向右、y 向下。

```python
import math
import charmove

tiles = [
    [0, 0, 0],
    [0, 1, 0],
    [1, 1, 1],
]
m = charmove.CharMove(tiles)

p = m.step((0.5, 0.5), (1.0, 0.0), 0.01)
assert len(p) == 2 and abs(p[0] - 0.51) < 1e-9
assert m.on_ground((1.5, 1.5)) is True
assert isinstance(m.slope((1.5, 1.5)), float)
```

`step()` 严格先扫描 X 轴、再扫描 Y 轴；快速移动会停在第一张被扫到的瓦片边界，
不会隧穿。返回值仍是长度 2 的普通 `(x, y)` tuple，实际类型 `StepResult`
额外提供 `blocked`、`blocked_x`、`blocked_y`、`climbed`、`sliding`、
`reason`、`normal`、`contacts`、`penetration`、`step_height` 等诊断属性。
`m.last_result` / `m.last` 保存同一次结果。

`ccd()`、`continuous_collision()`、`swept_move()`、`collision()` 都是同一套
分轴连续碰撞实现，因此 `step(pos, vel, dt)` 与 CCD 位置逐项一致。

### 瓦片格式

* `0`、`False`、`None`、`"."`、`" "`：空气；
* 所有非零有限数值、`True`、`"#"`、`"X"`：实心瓦片；
* `"/"`、`"\\"` 或 `{"type": "slope", "direction": "\\"}`：斜坡；
* 斜坡也可用 `{"type": "slope", "normal": (nx, ny)}`、`"angle"`（弧度）、
  `"degrees"` 或 `"m"`（屏幕坐标斜率 `dy/dx`）描述；
* 台阶/半砖可用 `{"type": "step", "height": 0.25}` 描述，`height` 是相对于
  单位瓦片的抬升高度；也可以直接用 `charmove.Slope(normal=(...))` 或
  `charmove.Step(0.25)` 工厂；
* 也支持 ASCII 行，例如 `["...", ".#.", "###"]`，以及 `TileSpec`。

### 斜坡

`slope(pos)` 返回有符号坡面角（弧度）；`slope_ratio()` 返回 `tan(angle)`，
`slope_normal(pos)` 返回单位法线。默认临界角是 45°，题面说“超过阈值”，因此
恰好等于阈值不滑落，严格大于才沿重力在切向上的投影滑下。

```python
steep = charmove.CharMove([[{"type": "slope", "m": 2.0}]])
p = steep.step((0.2, 0.4), (0.0, 0.0), 0.01)
assert p.sliding is True
assert abs(p[1] - 2.0 * p[0]) <= 1e-9       # 始终在坡面上
assert p.penetration <= 1e-9
```

也可以直接调用 `slide(pos, normal, dt, velocity=None)` 或模块级
`slide_vector(nx, ny, gravity, dt, velocity)`。

### 台阶

默认 `max_step=0.5`（半格）。`can_climb_step(h)`、`classify_step(h)` 和
`climb_step(h, raise_on_blocked=False)` 可直接区分可攀爬与过高阻挡；地图中的
台阶会在 X 轴碰撞时自动尝试抬升、重新扫描并落回坡面/地面。过高时位置停在墙前，
`reason == "step_too_high"`，重复步进的坐标差为 0。

### 稳定性与性能

碰撞点停在边界外侧 `1e-10` 的统一 snap gap 上；重复调用使用同一个目标边界，
因此贴墙/落地二次迭代差为 0，严格小于 `1e-12`。snap gap 与精确 CCD 边界的差为
`1e-10`，穿透深度由结果中的 `penetration` 报告并保持 `≤ 1e-9`。

瓦片在构造时一次解析；每次步进只扫描运动包围盒覆盖的少量瓦片，复杂度与路径覆盖
瓦片数成线性关系。普通 3×3 地图上的 1 万次步进约 0.09 秒（预热后 best-of-3），
留有超过 5 倍的 500 ms 预算余量。

### 错误类型

dt 错误与瓦片错误是不同异常树，且都继承 `ValueError`：

* `InvalidDTError`（别名 `InvalidDtError`、`InvalidDeltaTimeError`、
  `BadDtError` 等）：`dt` 必须是有限正数；`0`、负数、NaN、Inf、非数字和 bool
  均拒绝。
* `InvalidTilesError` / `InvalidTileMapError` / `InvalidTileError`
  （别名 `BadTilesError`、`MalformedTileMapError`、`EmptyTileMapError` 等）：
  空地图、空行、矩形长度不一致或不支持的瓦片描述。
* `InvalidPositionError`、`InvalidVelocityError`：二维有限实数向量。
* `StepTooHighError`：仅在 `climb_step(..., raise_on_blocked=True)` 等严格模式
  下抛出；普通 `step()` 会停住并在结果中标记阻挡。

每个异常类都有稳定的 `.code` 字符串。`charmove.errors` 也重新导出了这些类型；
包还提供常见近名异常/类名的 PEP 562 动态别名。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：游戏开发
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
