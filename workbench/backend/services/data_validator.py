"""兼容 shim：实体已下沉 sg_core/data_validator.py（T-976）。

sys.modules 转发——两名同一模块对象；新代码请直接 from sg_core import data_validator。
"""
import sys as _sys

from sg_core import data_validator as _mod

_sys.modules[__name__] = _mod
