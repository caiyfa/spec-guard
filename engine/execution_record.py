"""执行记录数据模型：一次场景执行的完整轨迹（可视化界面的数据源）。

所有记录仅包含只读数据；请求头中的 token 不落盘。
"""

from dataclasses import dataclass, field, asdict

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_SKIP = "SKIP"
VERDICT_BLOCKED = "BLOCKED"
# 版本化依赖（格式 2.0）：契约版本失配 / 上游缺失（默认不阻塞流水线，strict_deps 下退化为 BLOCKED）
VERDICT_DRIFT = "DRIFT"
VERDICT_ORPHANED = "ORPHANED"

# 失败归类
CAT_HTTP = "http_unexpected"
CAT_ASSERT = "assert_failed"
CAT_ORACLE = "oracle_mismatch"
CAT_DB = "db_mismatch"
CAT_POOL = "pool_unavailable"
CAT_UPSTREAM = "upstream_blocked"
CAT_ENV = "env_error"

# body_excerpt 截断上限
_MAX_STR = 500
_MAX_LIST = 20
_MAX_DEPTH = 8


def truncate(obj, _depth=0):
    """响应摘录截断：深度/字符串长度/列表长度设上限，防止 run.json 膨胀。"""
    if _depth >= _MAX_DEPTH:
        return "…"
    if isinstance(obj, str):
        return obj if len(obj) <= _MAX_STR else obj[:_MAX_STR] + f"…(共{len(obj)}字符)"
    if isinstance(obj, list):
        items = [truncate(v, _depth + 1) for v in obj[:_MAX_LIST]]
        if len(obj) > _MAX_LIST:
            items.append(f"…(共{len(obj)}项)")
        return items
    if isinstance(obj, dict):
        return {k: truncate(v, _depth + 1) for k, v in obj.items()}
    return obj


@dataclass
class StepTrace:
    """单步执行轨迹"""
    type: str                              # 步骤类型（call / set_var / db_query / select_emp / ...）
    request: dict = field(default_factory=dict)   # method/path/params（不含 Authorization）
    response_status: int = None
    duration_ms: int = 0
    body_excerpt: object = None
    note: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class AssertionTrace:
    expr: str                              # 人类可读断言描述
    passed: bool = False
    actual: object = None
    expected: object = None
    message: str = ""
    warnings: list = field(default_factory=list)   # WARN 三态：PASS 带 ⚠️（如 snapshot_frozen 宽松差异）

    def to_dict(self):
        return asdict(self)


@dataclass
class ExecutionRecord:
    """单场景完整执行记录"""
    scenario_id: str
    title: str = ""
    covers: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    priority: str = ""
    doc: dict = field(default_factory=dict)
    given: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)          # list[StepTrace]
    oracle_traces: list = field(default_factory=list)
    db_traces: list = field(default_factory=list)
    assertions: list = field(default_factory=list)     # list[AssertionTrace]
    verdict: str = VERDICT_FAIL
    failure: dict = None                               # {category, message, evidence}
    skip_reason: str = ""
    skip_category: str = "uncategorized"               # SKIP 归类（pool_empty/pool_leased_out/account_missing/db_unavailable/oracle_infra/uncategorized）
    duration_ms: int = 0
    upstream_of: str = ""                              # 非空表示该记录是作为哪个场景的上游执行的
    instance_no: int = 1                               # 实例序号（exclusive 依赖会产生多实例，>1 表示重跑份）
    dep_mode: str = ""                                 # 作为上游时的消费模式（shared/exclusive）

    def fail(self, category, message, evidence=None):
        self.verdict = VERDICT_FAIL
        self.failure = {"category": category, "message": message, "evidence": evidence}

    @property
    def warning_count(self):
        """WARN 三态：统计所有断言中的 warnings 条数（PASS 带 ⚠️ 的指标）"""
        return sum(len(a.warnings) for a in self.assertions if hasattr(a, 'warnings'))

    def to_dict(self):
        d = asdict(self)
        d["warning_count"] = self.warning_count   # @property 不被 asdict 收录，手动补充
        return d
