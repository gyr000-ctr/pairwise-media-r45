# threatdecay

## 题面（可直接粘贴）

仇恨表与滞回切换。约束：每目标独立半衰期，衰减与解析式 ≤1e-9；切换需超过当前目标 110% 才发生（滞回），切换事件序列与阈值规则逐项一致；多目标增量按序累加且与最终排序稳定；衰减到 0 后清空；10 万次不超过 300 ms；非法半衰期可区分报错。 工作目录为仓库内的 threatdecay/。 验收：cd threatdecay && python -m pytest tests -q。 实现只允许使用 Python 标准库。

## 运行方式

```bash
cd threatdecay && python -m pytest tests -q
```

初始 15 failed（实现前）。仅使用 Python 标准库。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：游戏开发
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
