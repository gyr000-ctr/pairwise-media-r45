"""combatframe 核心 API（初始未实现，仅标准库）。"""


class CombatFrame:
    def __init__(self, moves):
        """构造"""
        raise NotImplementedError

    def total(self, name):
        """总帧数"""
        raise NotImplementedError

    def window(self, name, kind):
        """帧窗口"""
        raise NotImplementedError

    def can_cancel(self, a, b, frame):
        """能否取消"""
        raise NotImplementedError
