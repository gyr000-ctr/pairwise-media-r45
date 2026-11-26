# combatframe

## 题面（可直接粘贴）

战斗帧数据与取消窗口。约束：每招的起手/判定/收招帧数之和等于总帧数（逐招校验）；帧区间取半开，判定段为 [startup, startup+active)；取消窗口只能从判定段起点开始，越界配置报错；取消合法性判定与帧区间代数一致（≤1e-12）；任意两招判定段重叠检测与区间相交定义一致；同招重复查询结果一致；10 万次判定不超过 300 ms；非法帧数（0 或负）可区分报错。 工作目录为仓库内的 combatframe/。 验收：cd combatframe && python -m pytest tests -q。 实现只允许使用 Python 标准库。

## 运行方式

```bash
cd combatframe && python -m pytest tests -q
```

初始 15 failed（实现前）。仅使用 Python 标准库。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：游戏开发
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
