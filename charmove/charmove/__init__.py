from .core import *  # noqa: F401,F403
from . import core as _core

# 让 ``import charmove; charmove.AnyNearNameError`` 能回退到 core 的动态别名。
def __getattr__(name):
    return getattr(_core, name)
