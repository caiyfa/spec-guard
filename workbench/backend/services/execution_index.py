"""兼容 shim：实体已下沉 sg_core/execution_index.py（T-975 依赖倒挂翻正）。

sys.modules 直接转发实体模块——`services.execution_index` 与 `sg_core.execution_index` 是同一模块对象，
存量 import / mock 打桩 / 私有成员访问零改动。新代码请直接 `from sg_core import execution_index`。
"""
import sys as _sys

from sg_core import execution_index as _mod

_sys.modules[__name__] = _mod
