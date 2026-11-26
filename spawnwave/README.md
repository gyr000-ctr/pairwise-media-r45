# spawnwave

## 题面（可直接粘贴）

波次预算分配（整数规划）。约束：每波数量×单位成本 ≤预算且贪心取最大；种类 ≤6 时必须与暴力最优解对照（总价值差 ≤0）；难度曲线为（波次、玩家等级）二维且单调不减，与解析式 ≤1e-9；同种子可复现；1 万波不超过 500 ms；非法预算可区分报错。 工作目录为仓库内的 spawnwave/。 验收：cd spawnwave && python -m pytest tests -q。 实现只允许使用 Python 标准库。

## 运行方式

```bash
cd spawnwave && python -m pytest tests -q
```

初始 15 failed（实现前）。仅使用 Python 标准库。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：游戏开发
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
