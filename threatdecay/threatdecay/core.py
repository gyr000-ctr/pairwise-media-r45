"""threatdecay 核心 API（初始未实现，仅标准库）。"""


class ThreatDecay:
    def __init__(self, half_life):
        """构造"""
        raise NotImplementedError

    def add(self, target, amount):
        """加仇恨"""
        raise NotImplementedError

    def tick(self, dt):
        """衰减"""
        raise NotImplementedError

    def current(self):
        """当前目标"""
        raise NotImplementedError
