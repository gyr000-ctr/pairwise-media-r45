"""charmove 异常类型的兼容导入位置。"""

from .core import *  # noqa: F401,F403
from . import core as _core


def __getattr__(name):
    return getattr(_core, name)
