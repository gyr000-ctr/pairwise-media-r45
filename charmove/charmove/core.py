"""charmove 核心 API（初始未实现，仅标准库）。"""


class CharMove:
    def __init__(self, tiles):
        """构造"""
        raise NotImplementedError

    def step(self, pos, vel, dt):
        """步进"""
        raise NotImplementedError

    def on_ground(self, pos):
        """是否着地"""
        raise NotImplementedError

    def slope(self, pos):
        """坡度"""
        raise NotImplementedError
