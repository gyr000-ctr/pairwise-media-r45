"""crafting 核心 API（初始未实现，仅标准库）。"""


class Crafting:
    def __init__(self, recipes):
        """构造"""
        raise NotImplementedError

    def order(self, item, n):
        """求解顺序"""
        raise NotImplementedError

    def missing(self, stock, item, n):
        """缺口"""
        raise NotImplementedError
