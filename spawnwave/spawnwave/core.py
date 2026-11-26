"""spawnwave 核心 API（初始未实现，仅标准库）。"""


class SpawnWave:
    def __init__(self, curve, costs, seed):
        """构造"""
        raise NotImplementedError

    def wave(self, n):
        """第 n 波"""
        raise NotImplementedError

    def budget(self, n):
        """预算"""
        raise NotImplementedError
