"""兼容 shim：实体已下沉 sg_core/feishu_paths.py（T-976 解 graph_index↔specflow 环）。

sys.modules 转发——两名同一模块对象，存量 import 零改动；
新代码请直接 from sg_core import feishu_paths。
"""
import sys as _sys

from sg_core import feishu_paths as _mod

_sys.modules[__name__] = _mod
