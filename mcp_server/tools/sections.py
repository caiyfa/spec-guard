"""兼容 shim：实体已下沉 sg_core/spec_sections.py（T-1023）。

章节提取纯函数被 mcp_server（read_spec/read_scenario）与 workbench
（anchor-refs 接口）共同消费，依 sg_core 共享内核定位下沉。
sys.modules 直接转发实体模块——`mcp_server.tools.sections` 与
`sg_core.spec_sections` 是同一模块对象，存量 import / mock 打桩零改动。
新代码请直接 `from sg_core import spec_sections`。
"""
import sys as _sys

from sg_core import spec_sections as _mod

_sys.modules[__name__] = _mod
