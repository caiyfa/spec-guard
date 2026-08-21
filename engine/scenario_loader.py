"""场景加载器：扫描场景库 YAML → Scenario 对象。

场景库目录与 spec 模块路径对齐（如 scenarios/employee/person-profile/），
一景一文件；套件元信息放在 _suite.yaml（不作为一个场景）。
"""

from dataclasses import dataclass, field

import yaml


class ScenarioLoadError(Exception):
    pass


@dataclass
class Scenario:
    id: str
    title: str = ""
    version: str = "0.1"                        # 契约版本（MAJOR.MINOR；0.x=活跃 delta 快照期）
    priority: str = "P1"
    tags: list = field(default_factory=list)
    doc: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)   # 归一化后 [{id, mode, version?, optional?}]
    flow: list = field(default_factory=list)
    teardown: list = field(default_factory=list)     # 清理步骤（与 flow 同语法，session 末 LIFO 执行）
    produces: list = field(default_factory=list)     # 产出资源声明 [{resource, state}]（文档化+调度提示）
    requires: dict = field(default_factory=dict)     # 2.3.0：执行依赖声明 {accounts:[], env:[], upstream:[]}（预检扫描用）
    verify: list = field(default_factory=list)
    suite: dict = field(default_factory=dict)     # 所属套件元信息（feature/module/spec_ref/...）
    path: str = ""                                # 源文件路径

    @property
    def covers(self):
        return self.doc.get("covers", []) if self.doc else []

    @property
    def dimensions(self):
        """doc.dimensions 测试维度（受控词表见 sg_core.test_dimensions；缺省 []）。"""
        return self.doc.get("dimensions", []) if self.doc else []

    @property
    def module(self):
        return self.suite.get("module", "")

    @property
    def depends_on_ids(self):
        return [d["id"] for d in self.depends_on]

    @property
    def depends_display(self):
        """依赖链展示用：独占依赖标注 (exclusive)"""
        return [d["id"] + ("(exclusive)" if d["mode"] == MODE_EXCLUSIVE else "")
                for d in self.depends_on]


MODE_SHARED = "shared"
MODE_EXCLUSIVE = "exclusive"


def _normalize_depends(raw, path):
    """depends_on 归一化（格式 2.0：支持 version 期望与 optional 可选依赖）。

    - "PP-PREP-001"                                    → {id, mode: shared}（接受任意版本）
    - {id: IS-PREP-001, mode: exclusive}               → 独占实例
    - {id: PP-RC-001, version: ^1}                     → 契约版本期望（^X 同主版本 / X.Y 精确）
    - {id: XX-001, optional: true}                     → 可选依赖（缺失时场景 SKIP 而非 ORPHANED）
    """
    deps = []
    for d in (raw or []):
        if isinstance(d, str):
            deps.append({"id": d, "mode": MODE_SHARED, "version": None, "optional": False})
        elif isinstance(d, dict) and d.get("id"):
            mode = d.get("mode", MODE_SHARED)
            if mode not in (MODE_SHARED, MODE_EXCLUSIVE):
                raise ScenarioLoadError(
                    f"{path}: depends_on.mode 非法: {mode}（仅支持 {MODE_SHARED}/{MODE_EXCLUSIVE}）")
            version = d.get("version")
            if version is not None:
                from engine.versioning import parse_version, VersionError
                exp = str(version).strip()
                try:
                    parse_version(exp[1:] if exp.startswith("^") else exp)
                except VersionError as e:
                    raise ScenarioLoadError(f"{path}: depends_on.version 非法: {e}")
                version = exp
            deps.append({"id": d["id"], "mode": mode, "version": version,
                         "optional": bool(d.get("optional"))})
        else:
            raise ScenarioLoadError(f"{path}: depends_on 项格式错误（应为场景 ID 或 {{id, mode?, version?, optional?}}）: {d}")
    return deps


def _normalize_produces(raw, path):
    """produces 声明校验：[{resource, state}]，state 可省略"""
    items = []
    for p in (raw or []):
        if not isinstance(p, dict) or not p.get("resource"):
            raise ScenarioLoadError(f"{path}: produces 项格式错误（应为 {{resource, state?}}）: {p}")
        items.append({"resource": p["resource"], "state": p.get("state", "")})
    return items


def _normalize_requires(raw, path):
    """2.3.0：requires 执行依赖声明归一化。

    {accounts: [别名], env: [点号路径], upstream: [场景ID]}。
    格式错误抛 ScenarioLoadError（T8 校验）；合法值按序去重。
    """
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ScenarioLoadError(f"{path}: requires 应为映射 {accounts/env/upstream}，实际: {raw}")
    out = {}
    for key in ("accounts", "env", "upstream"):
        val = raw.get(key)
        if val is None:
            continue
        if not isinstance(val, list) or not all(isinstance(x, str) and x.strip() for x in val):
            raise ScenarioLoadError(f"{path}: requires.{key} 应为非空字符串数组，实际: {val}")
        out[key] = list(dict.fromkeys(val))  # 去重保序
    return out


def _load_yaml(path):
    # K-025：libyaml 可用时用 C 解析器（语义与 SafeLoader 完全一致；
    # 实测 90 文件全量解析 0.55s → 0.27s，配合 scenario_store 指纹缓存消除重复解析）
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if hasattr(yaml, "CSafeLoader"):
        return yaml.load(text, Loader=yaml.CSafeLoader) or {}
    return yaml.safe_load(text) or {}


def load_suite_meta(suite_dir):
    """加载套件元信息（_suite.yaml），不存在返回空 dict"""
    import os
    suite_file = os.path.join(suite_dir, "_suite.yaml")
    if os.path.isfile(suite_file):
        return _load_yaml(suite_file)
    return {}


def _parse_scenario(path, suite_meta):
    raw = _load_yaml(path)
    sid = raw.get("id")
    if not sid:
        raise ScenarioLoadError(f"{path}: 缺少必填字段 id")
    flow = raw.get("flow") or []
    verify = raw.get("verify") or []
    if not flow and not verify:
        raise ScenarioLoadError(f"{path}: 机器读层缺失（flow/verify 均为空），场景不可执行")
    doc = raw.get("doc") or {}
    version = str(raw.get("version", "0.1"))
    from engine.versioning import parse_version, VersionError
    try:
        parse_version(version)
    except VersionError as e:
        raise ScenarioLoadError(f"{path}: version 非法: {e}")
    return Scenario(
        id=sid,
        title=raw.get("title", ""),
        version=version,
        priority=raw.get("priority", "P1"),
        tags=raw.get("tags", []) or [],
        doc=doc,
        depends_on=_normalize_depends(raw.get("depends_on"), path),
        flow=flow,
        teardown=raw.get("teardown") or [],
        produces=_normalize_produces(raw.get("produces"), path),
        requires=_normalize_requires(raw.get("requires"), path),
        verify=verify,
        suite=suite_meta,
        path=str(path),
    )


def load_scenarios(scenarios_root):
    """递归扫描场景库根目录，返回全部 Scenario（按 id 排序）。

    校验：id 全局唯一；doc 段缺失仅告警（不阻塞）。
    """
    import os

    scenarios = []
    warnings = []
    for dirpath, _dirnames, filenames in os.walk(scenarios_root):
        suite_meta = load_suite_meta(dirpath)
        for fn in sorted(filenames):
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            sc = _parse_scenario(path, suite_meta)
            if not sc.doc:
                warnings.append(f"{sc.id}: doc 人读层缺失（报告将缺少原始内容描述）")
            scenarios.append(sc)

    ids = [s.id for s in scenarios]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ScenarioLoadError(f"场景 id 重复: {sorted(dup)}")

    for w in warnings:
        print(f"[SpecGuard WARN] {w}")
    return sorted(scenarios, key=lambda s: s.id)


def load_module_scenarios(scenarios_root, module_path):
    """加载指定模块（如 employee/person-profile）下的场景"""
    import os
    module_dir = os.path.join(scenarios_root, module_path.replace("/", os.sep))
    if not os.path.isdir(module_dir):
        raise ScenarioLoadError(f"模块场景目录不存在: {module_dir}")
    suite_meta = load_suite_meta(module_dir)
    scenarios = []
    for fn in sorted(os.listdir(module_dir)):
        if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
            continue
        scenarios.append(_parse_scenario(os.path.join(module_dir, fn), suite_meta))
    ids = [s.id for s in scenarios]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ScenarioLoadError(f"场景 id 重复: {sorted(dup)}")
    return sorted(scenarios, key=lambda s: s.id)
