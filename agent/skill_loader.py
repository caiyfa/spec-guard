"""兼容 shim：实体已下沉 sg_core/skill_loader.py（T-976 解 agent↔mcp_server 环）。

sys.modules 转发——agent.skill_loader 与 sg_core.skill_loader 同一模块对象；
新代码请直接 from sg_core import skill_loader。
"""
import sys as _sys

from sg_core import skill_loader as _mod

_sys.modules[__name__] = _mod
