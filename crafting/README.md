# crafting

## 题面（可直接粘贴）

配方依赖与净产出求解。约束：拓扑排序且检测环（报出参与节点）；缺失材料给出缺口清单；必须支持副产品与循环配方，按线性方程组求净产出并与求解器对照（≤1e-9）；产量按最小可行批次缩放且中间产物不重复计算；1 万节点不超过 600 ms；非法配方可区分报错。 工作目录为仓库内的 crafting/。 验收：cd crafting && python -m pytest tests -q。 实现只允许使用 Python 标准库。

## 运行方式

```bash
cd crafting && python -m pytest tests -q
```

初始 15 failed（实现前）。仅使用 Python 标准库。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：游戏开发
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
