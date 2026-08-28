"""parallel_safety — 场景并行安全静态判定（T-1038，Rust 借用检查的静态前移）。

问题：V3 §7.2 DAG 分层并行的前置件——两个场景能不能并行，应该在执行前
从声明静态判定（读读共享、沾写互斥），而不是并行跑了靠租约运行时互堵。
本模块给出「当前声明下的最大理论并行度」与分层结果，供看板呈现与未来
T-802 执行槽池化消费。纯静态分析，不碰调度（当前执行仍串行）。

保守健全规则 v1：
  读-读            并行安全（query/validator 场景两两可并行）
  沾写（producer/modifier） 全局互斥——SIT 是共享被测库，写场景的数据面
              无法声明隔离（produces/consumes 未落地），诚实保守
  同账号写读       亦互斥（读可能撞上写中途状态，断言不稳）

未来细化（扩展点，代码留位）：
  - V3 §六 produces/consumes 资源声明落地后，按资源粒度做借用兼容
    （同资源才互斥，不同资源写写可并行——类比 Rust 按所有权的字段级 borrow）；
  - T-802 RunPool 消费本判定的分层结果做调度分组。
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime

from services.scenario_store import list_scenarios, scenarios_root

READ_CATEGORIES = {"query", "validator"}
WRITE_CATEGORIES = {"producer", "modifier"}
_CACHE_TTL = 60.0
_cache: dict = {"key": None, "ts": 0.0, "payload": None}


def invalidate_cache():
    _cache.update(key=None, ts=0.0, payload=None)


def _accounts_used(path: str) -> set[str]:
    """场景 flow 静态扫描使用的账号别名（call.as / as 直写）。"""
    import re
    from pathlib import Path
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return set()
    # 块式 as: default 与内联 {as: default} 两种形态
    return set(re.findall(r"\bas:\s*([A-Za-z_][\w-]*)", text))


def analyze_parallel_safety(refresh: bool = False) -> dict:
    """并行安全全景（60s 缓存）。"""
    key = str(scenarios_root())
    now = time.time()
    if (not refresh and _cache["payload"] is not None
            and _cache["key"] == key and now - _cache["ts"] < _CACHE_TTL):
        return _cache["payload"]
    payload = _build()
    _cache.update(key=key, ts=now, payload=payload)
    return payload


def _build() -> dict:
    from engine.scenario_loader import load_scenarios
    from services.scenario_store import scenarios_root as sroot

    summaries = {s["id"]: s for s in list_scenarios()}
    scenarios = load_scenarios(str(sroot()))
    dependents: dict[str, int] = defaultdict(int)
    for s in summaries.values():
        for d in s.get("depends_on") or []:
            dependents[d["id"]] += 1

    readers: list[dict] = []
    writers: list[dict] = []
    for sc in scenarios:
        info = summaries.get(sc.id) or {}
        category = info.get("category", "")
        row = {
            "id": sc.id,
            "title": sc.title,
            "category": category,
            "priority": info.get("priority", ""),
            "dependents": dependents.get(sc.id, 0),
            "accounts": sorted(_accounts_used(sc.path)),
        }
        if category in WRITE_CATEGORIES:
            writers.append(row)
        else:
            readers.append(row)

    writers.sort(key=lambda r: (-r["dependents"], r["priority"] != "P0", r["id"]))
    readers.sort(key=lambda r: r["id"])

    # 理论并行度（保守模型）：读层全并行；写场景与一切互斥 → 调度上等于
    # 「读层一批 + 写层逐个」，最大并行窗 = max(1, len(readers))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "totals": {
            "scenarios": len(readers) + len(writers),
            "readers": len(readers),
            "writers": len(writers),
            "max_parallelism": max(1, len(readers)),
            "model": "读-读并行安全；沾写全局互斥（produces/consumes 落地后按资源粒度细化）",
        },
        "writers": writers,
        "readers": readers,
    }
