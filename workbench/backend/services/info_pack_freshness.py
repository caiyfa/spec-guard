"""兼容 shim：实体已下沉 sg_core/info_pack_freshness.py（T-975 依赖倒挂翻正）。

sys.modules 直接转发实体模块——`services.info_pack_freshness` 与 `sg_core.info_pack_freshness` 是同一模块对象，
存量 import / mock 打桩 / 私有成员访问零改动。新代码请直接 `from sg_core import info_pack_freshness`。
"""
import sys as _sys

from sg_core import info_pack_freshness as _mod

_sys.modules[__name__] = _mod
