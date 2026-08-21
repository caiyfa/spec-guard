"""兼容 shim：实体已下沉 sg_core/draft_promote.py（T-975 依赖倒挂翻正）。

sys.modules 直接转发实体模块——`services.draft_promote` 与 `sg_core.draft_promote` 是同一模块对象，
存量 import / mock 打桩 / 私有成员访问零改动。新代码请直接 `from sg_core import draft_promote`。
"""
import sys as _sys

from sg_core import draft_promote as _mod

_sys.modules[__name__] = _mod
