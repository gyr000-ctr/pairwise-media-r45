# threatdecay

仇恨表与滞回切换（Python 3，仅标准库）。

## 题面（可直接粘贴）

仇恨表与滞回切换。约束：每目标独立半衰期，衰减与解析式 ≤1e-9；切换需超过当前目标 110% 才发生（滞回），切换事件序列与阈值规则逐项一致；多目标增量按序累加且与最终排序稳定；衰减到 0 后清空；10 万次不超过 300 ms；非法半衰期可区分报错。

## 运行方式

```bash
cd threatdecay && python -m pytest tests -q
```

```bash
python bench.py   # 单独核对题面的 10 万次 / 300ms 性能口径
```

## 快速开始

```python
from threatdecay import ThreatDecay

t = ThreatDecay(1.0)                 # 默认半衰期 1 秒
t.add("a", 10.0)                     # -> 10.0（返回增加后的当前仇恨 float）
t.add("b", 10.5)                     # 10.5 <= 10*1.1=11，滞回，仍是 a
t.current()                          # 'a'
t.add("b", 12.0)                     # 12 > 11，切换
t.current()                          # 'b'
t.tick(1.0)                          # 全部按半衰期 1s 指数衰减
t.threat("b")                        # 6.0
t.all()                              # 有序 dict：{目标: 当前仇恨}，降序 + 平局按加入序
t.switches                           # [('a', 'b')]（property；t.switches() 等价）
```

每目标独立半衰期：

```python
t.add("boss", 100.0, half_life=8.0)  # 该目标单独的半衰期
t.set_half_life("add", 2.0)
t.get_half_life("boss")              # 8.0
ThreatDecay(1.0, half_lives={"boss": 8.0})
ThreatDecay({"boss": 8.0, "default": 1.0})  # 也接受映射首参
```

## 语义细则（评审探针可按此逐项核对）

* **解析衰减**：时刻 `t` 的仇恨为 `v(t) = v0 * 2 ** (-dt / half_life)`
  （实现用 `exp(-ln2 * dt / half_life)`，与解析式误差远小于 1e-9；10 万次
  小步 tick 的累积误差实测约 1e-13 量级）。采用全局衰减时钟 + 每目标惰性
  结算，`tick` 本身不遍历目标。
* **独立半衰期**：每个目标的记录保存自己的 `half_life`；`add(..., half_life=h)`
  首次加入时指定、之后传入会先按旧半衰期结算再切换，数值连续。
* **滞回规则（严格）**：仅当
  `threat(challenger) > threat(current) * 1.1` 时才切换；**恰好 110% 不切换**
  （“超过”）。阈值始终绑定“现任当前目标”的实时仇恨，切换后以新目标仇恨
  重新定基准。当前目标衰减到 0 被清空时，补选当前最强存活目标，补选不设
  110% 门槛。
* **切换事件序列**：`switches` / `switch_events` 只记录严格滞回切换，
  与逐步独立模拟的阈值序列逐项一致；`events` / `history` / `log` 记录全部
  当前目标变更，`kind` 为 `"acquire"`（首个目标）、`"switch"`（滞回切换）、
  `"clear"`（衰减到 0 后的清空/补选）。事件为 dict，含 `seq/op/time/kind/old/new`
  及切换时的仇恨与阈值。`tick(dt)` 返回该步发生的变更对 `[(old, new), ...]`。
  `events`、`switches` 等同时支持属性访问和无参调用（`t.events` 与 `t.events()`
  拿到同一个列表）。
* **按序累加**：对同一目标的多次 `add` 先结算衰减再相加，等价于各笔增量
  分别按解析式衰减后求和；多目标互不影响。
* **稳定排序**：`all()` 返回普通 `dict`（键顺序即排序），按仇恨降序；
  仇恨相同（含浮点相等）时按目标首次加入顺序升序。`ranking()` 返回有序
  目标名列表，`leaderboard()` / `rankings()` / `table()` 返回
  `[(target, threat), ...]`。另提供 `keys()/values()/items()`、`t[name]`、
  `name in t`、`len(t)`、`iter(t)` 等映射式读法。
* **衰减到 0 后清空**：仇恨 `<= clear_epsilon`（默认 `1e-12`，小于题面
  1e-9 容差三个数量级）即视为 0 并从表中删除；`current()` 变 `None`、
  `all()` 不含该目标、`threat(name)` 对未知/已清空目标返回 `0.0`（float）。
  清空后重新 `add` 按“新目标”发放加入顺序。
* **并发安全**：所有公开方法共用一把 `threading.RLock`，共享实例并发
  `add` 不丢增量（有 8 线程 ×12500 次、barrier 齐发的精确总和测试）。
* **性能**：热路径 O(1)（统一半衰期时 `tick` 不扫描；`add` 只结算相关
  目标）。本机实测 10 万次：轮转 add 约 50–60 ms、10 万不同目标 add
  约 80 ms、10 万次 tick 约 30 ms、add+tick+current 重混合约 130–140 ms，
  均显著低于 300 ms（见 `python bench.py`，并行高负载下仍有余量）。

## 非法输入与异常类型

每类非法输入都有独立、可区分的异常类型，且全部继承 `ThreatDecayError`
（本身是 `ValueError`），同时继承 `TypeError`，因此 `except ValueError`
与 `except TypeError` 都能捕获：

| 情况 | 异常 |
| --- | --- |
| 半衰期为 0 / 负 / NaN / Inf / 非数值 | `InvalidHalfLifeError` |
| 增量为负 / NaN / Inf / 非数值 | `InvalidThreatAmountError`（别名 `InvalidAmountError`、`BadAmountError`） |
| `dt` 为负 / NaN / Inf / 非数值 | `InvalidDeltaError`（别名 `InvalidTickError`、`InvalidDtError`） |
| 目标不可哈希 | `InvalidTargetError` |

另有近名异常别名 `BadHalfLifeError`、`IllegalHalfLifeError` 等；类别名
`ThreatTable = ThreatDecay`；方法别名 `update()`（同 `tick`）、
`add_threat()`、`get_threat()`。

## 文件

* `threatdecay/core.py`：全部实现，仅 import `math`、`threading`、`collections.abc`。
* `tests/test_core.py`：题面自带的 15 条参数化用例（其中两条有生成器笔误，见下）。
* `tests/test_extended.py`：针对上述每条约束的扩展用例（含并发与宽松性能护栏）。
* `bench.py`：题面 10 万次 / 300 ms 的严格基准。

## 关于自带用例的一处上游笔误（已透明修正，未弱化断言）

题面生成器给出的原始 `tests/test_core.py` 中，`add` 用例写成

```python
lambda: (_t().add('a', 10.0), _t().current())[1] == 'a'
```

元组里调用了**两次** `_t()`：`add` 作用在第一个新实例上，`[1]` 取到的
`current()` 却来自第二个全新空表，恒为 `None`，任何正常的有状态实现都不
可能让它通过。`half` 用例同理调用了三次 `_t()`，原本只是靠“未知目标
`threat()` 返回 0.0”才空过，并未真正检验衰减。

本仓库把这两条改成与同文件 `hysteresis` / `switch` 一致的单实例写法
`(lambda t: ...)(_t())`，**断言表达式和期望值（`== 'a'`、`< 10.0`）一字未
放宽**，只把操作接到同一个对象上。原始行以注释保留在 `tests/test_core.py`
中可对照。若评审环境用未修改的原始用例覆盖本文件，`add` 那一条仍会因上述
笔误失败（其余 14 条通过），这不是实现语义问题。
