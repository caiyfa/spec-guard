"""变量插值器（T-999c 自 scenario_runner 抽出，行为零变化）。

规则：
- 字符串完全匹配 {{expr}} → 返回解析值（保留原始类型，如 int/list/dict）
- 字符串内嵌 {{expr}} → 字符串替换（str(value)）
- expr 支持点号路径（emp.no）/ 数组下标（records[0].id，jsonpath 兜底）/ fn 函数
"""

import re
import time
import uuid as _uuid

from jsonpath_ng import parse as jsonpath_parse


class RenderError(ValueError):
    """插值渲染后仍残留 {{ 占位符（ENG-T05/ENG-BUG-006）。

    书写错误的插值（缺右括号/空占位符）此前静默作为字面量发给 API，脏数据到
    断言/下游才暴露。ValueError 子类 → run_scenario 的 except 链归 CAT_SCENARIO
    （依赖 ENG-T01 的分类）。字面量 {{ 无转义语法（format_spec 已注明限制）。
    """



# ══════════════════════════════════════════════════════════
# 变量插值
# ══════════════════════════════════════════════════════════

# REQ-2：内置变量函数（运行时生成新值）
_FNS = {
    "fn.timestamp": lambda: str(int(time.time())),
    "fn.date": lambda: time.strftime("%Y%m%d"),
    "fn.uuid_short": lambda: _uuid.uuid4().hex[:8],
}


def _resolve(expr, ns):
    """变量插值解析：支持点号路径 + 数组下标 + fn 函数。

    解析顺序：
    1. fn 函数（fn.timestamp 等）→ 直接调用
    2. 点号路径（emp.no）→ 快速 dict 路径
    3. 数组下标/复杂路径 → jsonpath 兜底
    """
    expr = expr.strip()

    # REQ-2：fn 函数拦截
    if expr in _FNS:
        return _FNS[expr]()

    # 快路径：点号 dict 路径
    parts = expr.split(".")
    try:
        cur = ns
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            elif isinstance(cur, list) and p.isdigit():
                cur = cur[int(p)]
            else:
                raise KeyError(p)
        return cur
    except (KeyError, TypeError, IndexError):
        pass

    # REQ-1：jsonpath 兜底（数组下标 records[0].id、负索引 rows[-1]）
    try:
        matches = jsonpath_parse(f"$.{expr}").find(ns)
        if matches:
            return matches[0].value
    except Exception:
        pass

    raise KeyError(f"变量未定义: {expr}（可用键: {list(ns) if isinstance(ns, dict) else type(ns)}）")


# ENG-T05（ENG-BUG-006）：渲染结果残留占位符检测——写错的插值不再静默作为字面量发出
_PLACEHOLDER_LEFT = re.compile(r"\{\{")


def render(obj, ns):
    """递归插值：dict/list/str 中的 {{expr}} 全部替换

    残留扫描（ENG-T05）：字符串经 fullmatch/sub 处理后仍含 {{ → 抛 RenderError
    （归 CAT_SCENARIO）。注：fullmatch 分支的解析值来自变量，其内容含 {{ 属数据
    而非模板错误，不扫描。
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: render(v, ns) for k, v in obj.items()}
    if isinstance(obj, list):
        return [render(v, ns) for v in obj]
    if isinstance(obj, str):
        m = re.fullmatch(r"\{\{\s*(.+?)\s*\}\}", obj)
        if m:
            return _resolve(m.group(1), ns)          # 完全匹配：保留类型
        out = re.sub(r"\{\{\s*(.+?)\s*\}\}",
                     lambda mm: str(_resolve(mm.group(1), ns)), obj)
        if _PLACEHOLDER_LEFT.search(out):
            raise RenderError(f"未解析的插值占位符: {obj!r}"
                              f"（渲染结果残留 '{{'，检查是否缺右括号或变量名拼错）")
        return out
    return obj


