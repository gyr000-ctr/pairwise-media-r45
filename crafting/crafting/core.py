"""crafting 核心 API（仅使用 Python 标准库）。

数据模型
========
配方映射 ``{产品: 配方}``，支持三种配方写法：

1. ``(输入dict, 产出数量)``                —— 单产品
   例: ``{"axe": ({"wood": 1, "iron": 2}, 1)}``
2. ``(输入dict, 产出dict)``                —— 含副产品
   例: ``{"iron_ingot": ({"iron_ore": 2}, {"iron_ingot": 1, "slag": 1})}``
3. ``(输入dict, 产品名, 产出数量)``        —— 显式产品名（等价写法 1）

所有数量必须为正数（int/float，布尔值除外），NaN/Inf 一律拒绝。

能力
====
* 拓扑排序（确定性）与环检测，环上所有参与节点通过 ``CycleError.cycle`` 报出。
* 最小可行批次缩放（按单批产出向上取整，浮点带容差），副产品可冲抵需求。
* 缺口清单：仅统计无配方的原材料净缺口，中间产物不重复计算。
* 循环配方 / 副产品：建立净产出线性方程组 ``A x = d``，
  Tarjan SCC + 块三角回代，以 ``fractions.Fraction`` 精确求解，
  并用同构浮点求解器独立复核（残差 <= 1e-9）。
* 1 万节点 DAG 全流程 O(V+E)，线性求解同样近线性（稠密消元仅限循环小块）。
"""

import math
from fractions import Fraction
from collections import deque

__all__ = [
    "Crafting",
    "CraftingError",
    "InvalidRecipeError",
    "UnknownItemError",
    "CycleError",
    "UnsolvableError",
]

# 浮点求解器对照容差
SOLVER_TOL = 1e-9
# 批次向上取整的浮点容差，避免 1.0000000000000002 之类被多算一批
BATCH_EPS = 1e-12


class CraftingError(ValueError):
    """crafting 模块所有可区分错误的基类（同时是 ValueError）。"""


class InvalidRecipeError(CraftingError):
    """非法配方（结构错误、非正数量、NaN/Inf 等）。"""


class UnknownItemError(CraftingError):
    """请求了任何配方都无法生产的物品。"""

    def __init__(self, item, message=None):
        self.item = item
        super().__init__(message if message is not None else f"unknown item: {item!r}")


class CycleError(CraftingError):
    """配方依赖图存在环。``cycle`` 给出环上的全部参与节点。"""

    def __init__(self, cycle, message=None):
        self.cycle = list(cycle)
        super().__init__(
            message if message is not None
            else "recipe cycle detected involving: " + ", ".join(map(str, self.cycle))
        )


class UnsolvableError(CraftingError):
    """净产出线性方程组无唯一解 / 无法满足目标需求。"""


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _positive_finite(v):
    if not _is_number(v):
        return False
    # bool 已在 _is_number 中排除
    return v > 0 and v not in (float("inf"), float("-inf")) and v == v


def _ceil_div(num, den):
    """ceil(num / den)，带浮点容差；num/den 均为非负数值。"""
    q = num / den
    if isinstance(q, float):
        if q == float("inf"):
            raise InvalidRecipeError("required batch count is not finite")
        if q <= BATCH_EPS:
            return 0
        r = round(q)
        if abs(q - r) <= BATCH_EPS:
            return int(r)
        return math.ceil(q)
    return math.ceil(q)


class Crafting:
    """配方依赖与净产出求解器。"""

    # ------------------------------------------------------------------ #
    # 构造与配方规范化
    # ------------------------------------------------------------------ #
    def __init__(self, recipes):
        """规范化并校验配方表。

        非法配方抛出 :class:`InvalidRecipeError`（ValueError 子类），
        与未知物品、环、无解等错误可区分。
        """
        if not isinstance(recipes, dict):
            raise InvalidRecipeError("recipes must be a dict of {product: recipe}")

        # inputs[item] = {原料: 每批消耗}
        # outputs[item] = {产品: 每批产出}（含主产品与副产品）
        self.inputs = {}
        self.outputs = {}
        # producer[物品] = 负责生产它的配方键（主产品/副产品均可被生产）
        self.producer = {}

        for product, recipe in recipes.items():
            if not isinstance(product, str) or not product:
                raise InvalidRecipeError(f"recipe product must be a non-empty str, got {product!r}")
            if product in self.inputs:
                raise InvalidRecipeError(f"duplicate recipe for {product!r}")

            inputs, outputs = self._parse_recipe(product, recipe)
            self.inputs[product] = inputs
            self.outputs[product] = outputs
            for out_item in outputs:
                if out_item in self.producer:
                    raise InvalidRecipeError(
                        f"item {out_item!r} has multiple producers: "
                        f"{self.producer[out_item]!r} and {product!r}"
                    )
                self.producer[out_item] = product

        # 依赖邻接（节点为配方键），两类边：
        # 1) 需求边：配方原料若可生产，其生产者必须先于本配方
        #    （逆拓扑结算时，原料缺口会先触发对应配方定批）；
        # 2) 副产品供给边：本配方产出但由别的配方负责的物品，
        #    其生产者也必须先于本配方（副产品冲抵先到账）。
        # 复杂度 O(配方数 + 输入/输出条目总数)。
        self._deps = {}
        for product in self.inputs:
            deps = []
            seen = set()

            def add_dep(p, allow_self):
                if p is None or p in seen:
                    return
                if not allow_self and p == product:
                    return
                seen.add(p)
                deps.append(p)

            # 需求边：允许自环（配方消费自身产品 = 循环配方，须参与环检测）
            for name in self.inputs[product]:
                add_dep(self.producer.get(name), allow_self=True)
            # 供给边：自身主产品不算依赖，只连“别人负责生产”的副产品
            for out_item in self.outputs[product]:
                p = self.producer.get(out_item)
                add_dep(p, allow_self=False)
            self._deps[product] = deps

        self._all_items = set(self.producer)

    @staticmethod
    def _parse_recipe(product, recipe):
        if not isinstance(recipe, (tuple, list)) or len(recipe) < 2:
            raise InvalidRecipeError(
                f"recipe for {product!r} must be (inputs, output[, qty])"
            )

        inputs_raw = recipe[0]
        if not isinstance(inputs_raw, dict) or not inputs_raw:
            raise InvalidRecipeError(
                f"recipe for {product!r} needs a non-empty inputs dict"
            )
        inputs = {}
        for name, qty in inputs_raw.items():
            if not isinstance(name, str) or not name:
                raise InvalidRecipeError(f"ingredient name must be non-empty str in {product!r}")
            if not _positive_finite(qty):
                raise InvalidRecipeError(
                    f"ingredient {name!r} qty in recipe {product!r} must be positive finite, got {qty!r}"
                )
            inputs[name] = qty

        out_field = recipe[1]
        outputs = {}
        if isinstance(out_field, dict):
            if not out_field:
                raise InvalidRecipeError(f"recipe for {product!r} has empty outputs dict")
            for name, qty in out_field.items():
                if not isinstance(name, str) or not name:
                    raise InvalidRecipeError(f"output name must be non-empty str in {product!r}")
                if not _positive_finite(qty):
                    raise InvalidRecipeError(
                        f"output {name!r} qty in recipe {product!r} must be positive finite, got {qty!r}"
                    )
                outputs[name] = qty
        elif isinstance(out_field, str) and len(recipe) >= 3:
            # (inputs, product_name, qty)
            out_name, out_qty = out_field, recipe[2]
            if not out_name:
                raise InvalidRecipeError(f"empty output name in recipe {product!r}")
            if not _positive_finite(out_qty):
                raise InvalidRecipeError(
                    f"output qty in recipe {product!r} must be positive finite, got {out_qty!r}"
                )
            outputs[out_name] = out_qty
        elif _positive_finite(out_field):
            # (inputs, qty)
            outputs[product] = out_field
        else:
            raise InvalidRecipeError(
                f"unrecognized output spec in recipe for {product!r}: {out_field!r}"
            )

        if product not in outputs:
            # 配方键必须出现在自身产出中，否则依赖图归属无法确定
            raise InvalidRecipeError(
                f"recipe key {product!r} must appear among its outputs"
            )
        return inputs, outputs

    # ------------------------------------------------------------------ #
    # 图工具：可达子图、拓扑、环
    # ------------------------------------------------------------------ #
    def _reachable(self, target):
        """从 target 沿配方原料展开的可达集合（target 必须有配方）。"""
        seen = {target}
        stack = [target]
        while stack:
            cur = stack.pop()
            for nxt in self._deps[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    def _topo(self, nodes):
        """对节点子集做 Kahn 拓扑排序；检测到环时抛 :class:`CycleError`。

        返回拓扑序列（依赖在前，产品在后），按配方插入序确定，
        不受集合哈希随机化影响。
        """
        ordered = [k for k in self.inputs if k in nodes]
        indeg = {k: 0 for k in ordered}
        # 邻接表：依赖 -> 以它为输入的配方
        adj = {k: [] for k in ordered}
        for k in ordered:
            for dep in self._deps[k]:
                if dep in indeg:
                    indeg[k] += 1
                    adj[dep].append(k)

        queue = deque(k for k in ordered if indeg[k] == 0)
        order = []
        while queue:
            cur = queue.popleft()
            order.append(cur)
            for nxt in adj[cur]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)

        if len(order) != len(ordered):
            raise CycleError(self._cycle_nodes(ordered))
        return order

    def _scc(self, nodes):
        """迭代 Tarjan 强连通分量，返回分量列表（每个分量为节点列表）。"""
        index_of = {}
        lowlink = {}
        on_stack = set()
        stack = []
        sccs = []
        counter = 0

        for start in nodes:
            if start in index_of:
                continue
            # 迭代 DFS：栈帧为 (节点, 下一条邻接边的下标)
            work = [(start, 0)]
            index_of[start] = lowlink[start] = counter
            counter += 1
            stack.append(start)
            on_stack.add(start)
            while work:
                v, edge_i = work[-1]
                neighbors = self._deps[v]
                if edge_i < len(neighbors):
                    w = neighbors[edge_i]
                    work[-1] = (v, edge_i + 1)
                    if w not in index_of:
                        index_of[w] = lowlink[w] = counter
                        counter += 1
                        stack.append(w)
                        on_stack.add(w)
                        work.append((w, 0))
                    elif w in on_stack:
                        lowlink[v] = min(lowlink[v], index_of[w])
                else:
                    work.pop()
                    if work:
                        parent = work[-1][0]
                        lowlink[parent] = min(lowlink[parent], lowlink[v])
                    if lowlink[v] == index_of[v]:
                        comp = []
                        while True:
                            w = stack.pop()
                            on_stack.discard(w)
                            comp.append(w)
                            if w == v:
                                break
                        sccs.append(comp)
        return sccs

    def _cycle_nodes(self, nodes):
        """精确返回参与环的节点。

        环节点 = 大小 > 1 的 SCC，或含自环的单节点 SCC。
        仅依赖环上的下游节点不会被误报。
        """
        cycle = []
        node_set = set(nodes)
        for comp in self._scc(list(nodes)):
            if len(comp) > 1:
                cycle.extend(comp)
            else:
                v = comp[0]
                if v in self._deps[v] and v in node_set:
                    cycle.append(v)
        return sorted(cycle)

    def cycle_nodes(self):
        """返回整张配方图中参与环的全部节点；无环返回空列表。"""
        try:
            self._topo(set(self.inputs))
        except CycleError as exc:
            return exc.cycle
        return []

    def topo_order(self, item):
        """纯拓扑序列（配方键列表，依赖在前）；有环抛 :class:`CycleError`。"""
        if item not in self.producer:
            raise UnknownItemError(item)
        nodes = self._reachable(self.producer[item])
        return self._topo(nodes)

    # ------------------------------------------------------------------ #
    # DAG 规划：最小可行批次 + 缺口
    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_count(n):
        if not _is_number(n):
            raise InvalidRecipeError(f"amount must be a number, got {n!r}")
        if n != n or n in (float("inf"), float("-inf")):
            raise InvalidRecipeError(f"amount must be finite, got {n!r}")
        if n <= 0:
            raise InvalidRecipeError(f"amount must be positive, got {n!r}")

    def _check_stock(self, stock):
        if stock is None:
            return {}
        if not isinstance(stock, dict):
            raise InvalidRecipeError("stock must be a dict of {item: qty}")
        clean = {}
        for k, v in stock.items():
            if not isinstance(k, str) or not k:
                raise InvalidRecipeError(f"bad stock item name: {k!r}")
            if not _is_number(v) or v != v or v < 0:
                raise InvalidRecipeError(f"stock qty for {k!r} must be non-negative finite, got {v!r}")
            clean[k] = v
        return clean

    def plan(self, item, n, stock=None):
        """DAG 完整生产计划。

        返回 dict：
          ``order``     : [(配方键, 批次数), ...] 依赖在前的执行序列
          ``batches``   : {配方键: 批次数}
          ``demand``    : {可生产物品: 毛需求}（含目标 n）
          ``supply``    : {可生产物品: 总供给（含副产品与库存）}
          ``net``       : {物品: 净产出（产出-消耗，副产品计入）}
          ``materials`` : {原材料: 总消耗}
          ``shortage``  : {原材料: 扣除库存后的净缺口（仅 >0）}
        """
        self._check_count(n)
        stock = self._check_stock(stock)
        if not self.inputs:
            # 空配方表：没有任何可调度的配方，物品只能视为原材料
            gap = n - stock.get(item, 0)
            shortage = {item: gap} if gap > BATCH_EPS else {}
            return {
                "order": [],
                "batches": {},
                "demand": {item: n},
                "supply": {item: stock.get(item, 0)},
                "net": {item: -n},
                "materials": {item: n},
                "shortage": shortage,
            }
        if item not in self.producer:
            raise UnknownItemError(item)

        root = self.producer[item]
        nodes = self._reachable(root)
        topo = self._topo(nodes)  # 有环则抛 CycleError

        # 可达节点中所有可生产物品（含只作为副产品出现的物品）
        producible = set()
        for k in nodes:
            producible.update(self.outputs[k])

        demand = {k: 0.0 for k in producible}
        supply = {k: float(stock.get(k, 0)) for k in producible}
        demand[item] = n
        batches = {}

        # 逆拓扑：每个配方在其全部下游需求（含副产品冲抵）到账后结算。
        # 需求边保证原料缺口先触发对应配方；供给边保证副产品先到账。
        # 一个配方可同时服务多个物品（主产品+副产品），取各物品所需
        # 批次数的最大值作为该配方的最小可行批次；中间产物不重复计算。
        for cur in reversed(topo):
            b_need = 0
            for out_item, per_batch in self.outputs[cur].items():
                if out_item not in demand:
                    continue
                gap = demand[out_item] - supply[out_item]
                if gap > BATCH_EPS:
                    b_need = max(b_need, _ceil_div(gap, per_batch))
            batches[cur] = b_need
            if b_need:
                for out, qty in self.outputs[cur].items():
                    if out in demand:
                        supply[out] += b_need * qty
                for ing, qty in self.inputs[cur].items():
                    used = b_need * qty
                    if ing in demand:
                        demand[ing] += used
                    # 原材料在 materials 阶段统一汇总

        # 净产出 = 总产出（含副产品）- 总消耗
        flow = {}
        for cur, b in batches.items():
            if b == 0:
                continue
            for out, qty in self.outputs[cur].items():
                flow[out] = flow.get(out, 0.0) + b * qty
            for ing, qty in self.inputs[cur].items():
                flow[ing] = flow.get(ing, 0.0) - b * qty

        materials = {}
        shortage = {}
        for mat, val in flow.items():
            if mat not in self.producer:  # 无任何配方生产 => 原材料
                consumed = -val if val < 0 else 0.0
                materials[mat] = consumed
                gap = consumed - stock.get(mat, 0)
                if gap > BATCH_EPS:
                    shortage[mat] = gap

        # 兜底：任何未被满足的可生产物品需求（理论上仅异常数据才会走到）
        for cur, d in demand.items():
            if supply[cur] + BATCH_EPS < d:
                shortage[cur] = shortage.get(cur, 0.0) + (d - supply[cur])

        return {
            "order": [(k, batches[k]) for k in topo],
            "batches": batches,
            "demand": demand,
            "supply": supply,
            "net": flow,
            "materials": materials,
            "shortage": shortage,
        }

    def order(self, item, n):
        """求解生产顺序：返回 ``[(物品, 最小可行批次数), ...]``（依赖在前）。

        环 => :class:`CycleError`；未知物品 => :class:`UnknownItemError`；
        非法数量 => :class:`InvalidRecipeError`。
        """
        return self.plan(item, n)["order"]

    def missing(self, stock, item, n):
        """扣除库存后的原材料缺口清单（仅含缺口为正的原材料）。"""
        return self.plan(item, n, stock)["shortage"]

    # ------------------------------------------------------------------ #
    # 净产出线性方程组（支持循环配方 / 副产品）
    # ------------------------------------------------------------------ #
    def net_output(self, batches):
        """给定各配方批次数，求每个物品的净产出（产出 - 消耗）。

        循环配方同样适用；返回 {物品: 净产出}，负值表示净消耗。
        """
        if not isinstance(batches, dict):
            raise InvalidRecipeError("batches must be a dict of {recipe_item: count}")
        flow = {}
        for item, b in batches.items():
            if item not in self.inputs:
                raise UnknownItemError(item)
            if not _is_number(b) or b != b or b < 0:
                raise InvalidRecipeError(f"batch count for {item!r} must be non-negative finite")
            if b == 0:
                continue
            for out, qty in self.outputs[item].items():
                flow[out] = flow.get(out, 0.0) + b * qty
            for ing, qty in self.inputs[item].items():
                flow[ing] = flow.get(ing, 0.0) - b * qty
        return flow

    @staticmethod
    def _to_fraction(v):
        """安全转 Fraction；NaN/Inf 转成可区分的 InvalidRecipeError。"""
        try:
            return Fraction(v)
        except (TypeError, ValueError, OverflowError) as exc:
            raise InvalidRecipeError(f"quantity must be finite rational, got {v!r}") from exc

    @staticmethod
    def _gauss_fraction(A, b):
        """Fraction 精确 Gauss-Jordan，返回解 x（Fraction 列表）。"""
        n = len(b)
        M = [list(map(Fraction, A[i])) + [Fraction(b[i])] for i in range(n)]
        row = 0
        for col in range(n):
            pivot = next((r for r in range(row, n) if M[r][col] != 0), None)
            if pivot is None:
                raise UnsolvableError("linear system is singular (no unique solution)")
            M[row], M[pivot] = M[pivot], M[row]
            piv = M[row][col]
            M[row] = [v / piv for v in M[row]]
            for r in range(n):
                if r != row and M[r][col] != 0:
                    factor = M[r][col]
                    M[r] = [a - factor * c for a, c in zip(M[r], M[row])]
            row += 1
        return [M[i][n] for i in range(n)]

    @staticmethod
    def _gauss_float(A, b):
        """浮点 Gauss-Jordan（循环块复核用），返回 (解, 最大残差)。"""
        n = len(b)
        M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]
        row = 0
        for col in range(n):
            pivot = max(range(row, n), key=lambda r: abs(M[r][col]))
            if abs(M[pivot][col]) < 1e-15:
                raise UnsolvableError("float solver: singular matrix")
            M[row], M[pivot] = M[pivot], M[row]
            piv = M[row][col]
            M[row] = [v / piv for v in M[row]]
            for r in range(n):
                if r != row:
                    factor = M[r][col]
                    if factor:
                        M[r] = [a - factor * c for a, c in zip(M[r], M[row])]
            row += 1
        x = [M[i][n] for i in range(n)]
        res = 0.0
        for i in range(n):
            r = sum(A[i][j] * x[j] for j in range(n)) - b[i]
            res = max(res, abs(r))
        return x, res

    def _block_triangular_solve(self, A, d, comps, idx, exact):
        """SCC 凝聚的块三角求解，精确（Fraction）或浮点两种模式同构实现。

        ``A`` 为稀疏行 dict（{列号: 系数}）。按后驱->前驱的凝聚序回代：
        DAG 分量（单节点且无自环）单变量定解；循环分量抽取稠密小块
        做 Gauss-Jordan。分量被处理时，其行内所有块外变量均已解出。
        """
        m = len(d)
        zero = Fraction(0) if exact else 0.0
        x = [None] * m
        comp_id = {}
        for ci, comp in enumerate(comps):
            for v in comp:
                comp_id[v] = ci

        # 凝聚边：ci 依赖前驱 cj。回代要按“后驱先、前驱后”，
        # 即对反向图做 Kahn：统计每个分量的后驱数，后驱为 0 者先解。
        preds_of = [set() for _ in comps]
        succs_of = [set() for _ in comps]
        for ci, comp in enumerate(comps):
            for v in comp:
                for w in self._deps[v]:
                    cj = comp_id.get(w)
                    if cj is not None and cj != ci:
                        preds_of[ci].add(cj)
                        succs_of[cj].add(ci)
        # 后驱计数（反向图入度）
        out_deg = [len(succs_of[ci]) for ci in range(len(comps))]
        ready = [ci for ci, d in enumerate(out_deg) if d == 0]
        ordered_comps = []
        deg_work = list(out_deg)
        while ready:
            ci = ready.pop(0)
            ordered_comps.append(ci)
            for pred in preds_of[ci]:       # 本分量解出后，前驱少一个后驱
                deg_work[pred] -= 1
                if deg_work[pred] == 0:
                    ready.append(pred)

        done = 0
        for ci in ordered_comps:
            done += 1
            rows = [idx[v] for v in comps[ci]]
            cyclic_block = len(rows) > 1 or comps[ci][0] in self._deps[comps[ci][0]]

            # RHS = 需求 - 块外已知列的贡献
            rhs = []
            for i in rows:
                val = d[i]
                for j, a in A[i].items():
                    if x[j] is not None:
                        val -= a * x[j]
                rhs.append(val)

            if not cyclic_block:
                i = rows[0]
                coef = A[i].get(i, zero)
                if coef == zero:
                    raise UnsolvableError(f"no unique batch for recipe {comps[ci][0]!r}")
                x[i] = rhs[0] / coef
            else:
                # 抽取循环块对应的稠密小矩阵
                block = [[A[i].get(j, zero) for j in rows] for i in rows]
                if exact:
                    xb = self._gauss_fraction(block, rhs)
                else:
                    xb, _ = self._gauss_float(block, rhs)
                for pos, j in enumerate(rows):
                    x[j] = xb[pos]

        if done != len(comps) or any(v is None for v in x):
            raise UnsolvableError("underdetermined linear system")
        return x

    def solve(self, item, n, tol=SOLVER_TOL):
        """线性方程组净产出求解（支持循环配方与副产品）。

        净产出方程为 ``A x = d``（行=可生产物品，列=配方，
        系数=单批净产出）。求解策略：

        * Tarjan 求 SCC，在凝聚 DAG 上按后驱->前驱回代；
        * DAG 分量单变量前代/回代定解（O(V+E)，``Fraction`` 精确值）；
        * 仅对循环 SCC 抽取稠密小块做 Gauss-Jordan
          （循环配方通常规模很小），纯 DAG 不触发任何稠密消元；
        * 再以同构的浮点块三角求解独立复核，稀疏残差
          最大值须 <= ``tol``（默认 1e-9）。

        返回 dict：
          ``batches``   : {配方物品: Fraction 批次数（允许分数批）}
          ``batches_f`` : {配方物品: float 批次数}
          ``net``       : {物品: float 净产出}
          ``materials`` : {原材料: float 净消耗}
          ``residual``  : 浮点复核最大残差
        """
        self._check_count(n)
        if not _is_number(tol) or tol <= 0 or tol != tol:
            raise InvalidRecipeError("tol must be positive finite")
        if item not in self.producer:
            raise UnknownItemError(item)

        root = self.producer[item]
        nodes = self._reachable(root)
        items = [k for k in self.inputs if k in nodes]   # 插入序，确定排序
        idx = {k: i for i, k in enumerate(items)}
        m = len(items)

        # 稀疏净产出矩阵：每行 {列号: 系数}，仅存非零元。
        # 行=可生产物品，列=配方，系数=单批净产出（Fraction 精确值）。
        A = [{} for _ in range(m)]
        for j, recipe_item in enumerate(items):
            for ing, qty in self.inputs[recipe_item].items():
                if ing in idx:
                    i = idx[ing]
                    A[i][j] = A[i].get(j, Fraction(0)) - self._to_fraction(qty)
            for out, qty in self.outputs[recipe_item].items():
                if out in idx:
                    i = idx[out]
                    A[i][j] = A[i].get(j, Fraction(0)) + self._to_fraction(qty)
        target_row = item if item in idx else root
        d = [self._to_fraction(n) if k == target_row else Fraction(0) for k in items]

        # SCC 凝聚后的块三角消元（精确 Fraction）
        comps = self._scc(items)
        x_frac = self._block_triangular_solve(A, d, comps, idx, exact=True)

        if any(v < 0 for v in x_frac):
            raise UnsolvableError("solution requires negative batches (demand infeasible)")

        # 浮点独立复核：同构块三角求解（独立代码路径，浮点运算）
        Af = [{j: float(a) for j, a in row.items()} for row in A]
        df = [float(v) for v in d]
        x_float = self._block_triangular_solve(Af, df, comps, idx, exact=False)
        # 稀疏残差（只遍历非零元，O(非零条目数)）
        residual = 0.0
        for i in range(m):
            r = -df[i]
            for j, a in Af[i].items():
                r += a * x_float[j]
            residual = max(residual, abs(r))
        if residual > tol:
            raise UnsolvableError(f"solver cross-check residual {residual:.3g} > tol {tol:.3g}")
        # 两套解本身也要一致
        for f_exact, f_approx in zip(x_frac, x_float):
            if abs(float(f_exact) - f_approx) > max(tol, 1e-12):
                raise UnsolvableError("exact and float solvers disagree beyond tolerance")

        batches = {k: x_frac[idx[k]] for k in items}
        batches_f = {k: x_float[idx[k]] for k in items}

        flow = {}
        for recipe_item, b in batches.items():
            if b == 0:
                continue
            for out, qty in self.outputs[recipe_item].items():
                flow[out] = flow.get(out, 0.0) + float(b) * qty
            for ing, qty in self.inputs[recipe_item].items():
                flow[ing] = flow.get(ing, 0.0) - float(b) * qty

        materials = {k: -v for k, v in flow.items() if k not in self.producer and v < 0}

        # 需求满足性校验
        if flow.get(item, 0.0) + tol < n:
            raise UnsolvableError("solved net output does not cover demand")

        return {
            "batches": batches,
            "batches_f": batches_f,
            "net": flow,
            "materials": materials,
            "residual": residual,
        }

    def check_solver(self, item, n, tol=SOLVER_TOL):
        """对照求解器：返回浮点复核的最大残差（<= tol 即通过）。"""
        return self.solve(item, n, tol)["residual"]
