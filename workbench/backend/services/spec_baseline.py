"""兼容 shim：实体已下沉 sg_core/spec_baseline.py（T-975 依赖倒挂翻正）。

sys.modules 直接转发实体模块——`services.spec_baseline` 与 `sg_core.spec_baseline` 是同一模块对象，
存量 import / mock 打桩 / 私有成员访问零改动。新代码请直接 `from sg_core import spec_baseline`。
"""
import sys as _sys

from sg_core import spec_baseline as _mod

_sys.modules[__name__] = _mod
