"""schema 结构断言（fuzzy-match-lite，T-501）——Karate-lite 子集，纯 Python 零依赖。

匹配语义（只实现这些、不多做，施工规格见《引擎升级建议-第三批》§6.2）：
- 类型标记：`#string` / `#number` / `#boolean` / `#null`；字面值 = 精确相等（==，
  JSON 语义下 bool 与 number 不混——Python True == 1 的坑在此显式排除）
- 可选键：`##key`（键可不存在，存在则按规则匹配）
- 数组模式：`#[] <rule>`（数组每元素匹配 rule，空数组通过）
- 对象：键集严格匹配（多出未声明键 = 失败——结构漂移检测的核心语义）；全部嵌套递归
- 明确不支持：`#regex`、`#?` JS 表达式、`#(var)` 引用、`#present` 等扩展——有真实需求再扩

场景写法（oracle 参数化形式，verify 分发走注册表，冻结层执行器零改动）：

    verify:
      - oracle:
          name: schema_match
          params:
            of: createResp          # save 引用，缺省 resp；指向 call 产出取 ["json"]，其余裸值直通（U-1）
            spec:
              code: 200
              data:
                id: "#number"
                name: "#string"
                tags: "#[] #string"
                remark: "##string"  # 可选键

注册：register_builtin_oracles 挂在 conftest.py 与 mcp_server/tools/live_registry.py
（register_builtin_steps 旁），两处缺一 validator V9 幻觉拦截就查不到本断言器。
"""

from engine.scenario_runner import render

_TYPE_CHECKS = {
    "#string": lambda v: isinstance(v, str),
    "#number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "#boolean": lambda v: isinstance(v, bool),
    "#null": lambda v: v is None,
}

_SUPPORTED_HINT = "支持：#string/#number/#boolean/#null、#[] 数组模式、## 可选键"


def match(spec, actual):
    """fuzzy-match-lite 匹配核心：通过返回 None，失败返回字段级路径消息。

    纯函数，不依赖 rctx/requests，单测直接喂 dict。
    返回消息形如 `$.data.list[2].status: 期望 #string，实际 42`。
    """
    return _match(spec, actual, "$")


def _match(spec, actual, path):
    if isinstance(spec, dict):
        return _match_dict(spec, actual, path)
    if isinstance(spec, str) and spec.startswith("#"):
        return _match_marker(spec, actual, path)
    # 字面值精确相等（含字面 list；bool 与 number 不混）
    if spec == actual and isinstance(spec, bool) == isinstance(actual, bool):
        return None
    return f"{path}: 期望 {spec!r}，实际 {actual!r}"


def _match_dict(spec, actual, path):
    if not isinstance(actual, dict):
        return f"{path}: 期望对象，实际 {actual!r}"
    required, optional = {}, {}
    for k, v in spec.items():
        if isinstance(k, str) and k.startswith("##"):
            optional[k[2:]] = v
        else:
            required[k] = v
    for k in required:
        if k not in actual:
            return f"{path}.{k}: 缺少必需键"
    declared = set(required) | set(optional)
    for k in actual:
        if k not in declared:
            return f"{path}: 多出未声明键 {k!r}（结构漂移）"
    for k, v in spec.items():
        key = k[2:] if isinstance(k, str) and k.startswith("##") else k
        if key in actual:
            fail = _match(v, actual[key], f"{path}.{key}")
            if fail:
                return fail
    return None


def _match_marker(marker, actual, path):
    if marker.startswith("#[]"):
        rule = marker[3:].strip()
        if not isinstance(actual, list):
            return f"{path}: 期望数组（{marker}），实际 {actual!r}"
        for i, item in enumerate(actual):
            fail = _match(rule, item, f"{path}[{i}]")
            if fail:
                return fail
        return None
    check = _TYPE_CHECKS.get(marker)
    if check is None:
        return f"{path}: 不支持的 schema 标记 {marker!r}（{_SUPPORTED_HINT}）"
    if check(actual):
        return None
    return f"{path}: 期望 {marker}，实际 {actual!r}"


def oracle_schema_match(params, rctx, ns, record):
    """schema 结构断言（fuzzy-match-lite）：params={of?, spec}，of 缺省 resp；spec 支持 #string/#number/#boolean/#null、## 可选键、#[] 数组模式与嵌套递归，对象键集严格"""
    params = render(params, ns) or {}
    spec = params.get("spec")
    if spec is None:
        raise AssertionError("schema_match 缺少 spec 参数")
    of = params.get("of", "resp")
    target = ns.get(of)
    if target is None:
        raise AssertionError(f"schema_match 找不到断言目标变量: {of}")
    # U-1：call 产出取 ["json"]，其余（db_query 裸数组 / python 产出 / set_var 值）直通
    payload = target["json"] if isinstance(target, dict) and "json" in target else target
    fail = match(spec, payload)
    if fail:
        raise AssertionError(f"schema 不匹配（of={of}）：{fail}")


def register_builtin_oracles(registry):
    """注册引擎内建断言器（与 register_builtin_steps 同位调用）。"""
    registry.oracle("schema_match", oracle_schema_match)
