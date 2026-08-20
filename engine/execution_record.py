"""执行记录数据模型：一次场景执行的完整轨迹（可视化界面的数据源）。

所有记录仅包含只读数据；请求头中的 token 不落盘。
"""

from dataclasses import asdict, dataclass, field

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_SKIP = "SKIP"
VERDICT_BLOCKED = "BLOCKED"
# 版本化依赖（格式 2.0）：契约版本失配 / 上游缺失（默认不阻塞流水线，strict_deps 下升格为 FAIL）
VERDICT_DRIFT = "DRIFT"
VERDICT_ORPHANED = "ORPHANED"

# 失败归类（ENG-T01：常量表 7 → 5）
# 删除 CAT_HTTP / CAT_DB / CAT_POOL：网络异常归 CAT_ENV 属诚实语义；DB 失败已有
# skip_category=db_unavailable 与 CAT_ORACLE 覆盖；pool 语义与 skip_category 的
# pool_empty 重复（见 docs/架构升级/ENG-T01-失败归类体系改造.md §3.1）。
CAT_ASSERT = "assert_failed"          # 断言失败（status/json/oracle 断言不通过）
CAT_ORACLE = "oracle_mismatch"        # DB 校对断言不通过
CAT_UPSTREAM = "upstream_blocked"     # 上游未通过（BLOCKED 场景的 skip_category，非 fail 分类）
CAT_ENV = "env_error"                 # 环境/未知错误（网络异常、真正的环境缺口）
CAT_SCENARIO = "scenario_error"       # 场景编写错误（未定义变量 / 未注册 tool / jsonpath 拼错 / 脚本异常）
# ENG-T02 追加（契约门禁类，归属见 docs/架构升级/ENG-T02-契约版本门禁强化.md §3.4）：
CAT_CONTRACT_DRIFT = "contract_drift"     # 契约版本漂移（DRIFT；strict_deps 下 FAIL 的归类）
CAT_CONTRACT_ORPHAN = "contract_orphan"   # 上游依赖缺失（ORPHANED 的归类）

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
    request: dict = field(default_factory=dict)   # method/path/params/body（不含 Authorization）
    response_status: int = None
    duration_ms: int = 0
    body_excerpt: object = None            # 响应体摘要（截断，用于快速展示）
    trace_id: str = ""                     # 请求跟踪 ID（ifelc-trace_id，网关全链追踪）
    response_headers: dict = field(default_factory=dict)  # 完整响应头
    response_body: object = None           # 完整响应体（未截断，用于详细查询）
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
        d["saved_vars"] = truncate(getattr(self, "saved_vars", {}))
        return d
