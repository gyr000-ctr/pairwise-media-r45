# charmove

## 题面（可直接粘贴）

角色移动与瓦片碰撞解算。约束：分轴解算（先 X 后 Y）且与连续碰撞检测结果一致（≤1e-9）；斜坡法线决定滑落，坡度超过阈值时沿坡滑下且不穿地（穿透 ≤1e-9）；台阶高度不超过阈值时可攀爬，超过则被挡住（可区分）；贴墙时位置收敛不抖动（二次迭代差 ≤1e-12）；1 万次步进不超过 500 ms；非法 dt 与非法瓦片可区分报错。 工作目录为仓库内的 charmove/。 验收：cd charmove && python -m pytest tests -q。 实现只允许使用 Python 标准库。

## 运行方式

```bash
cd charmove && python -m pytest tests -q
```

初始 15 failed（实现前）。仅使用 Python 标准库。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：游戏开发
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
