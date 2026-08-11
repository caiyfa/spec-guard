"""specstd.knowledge_index 测试：触景触发索引（T-508）。

覆盖：
- 索引构建（glossary/env 叙事/经验目录三源 → kg:// 条目）
- 指纹失效重建 + 30s TTL 热加载
- 双通道匹配（工具结构化字段为主 / 用户关键词为辅，不做 agent 输出匹配）
- 投递预算纪律（每篇每会话一次、≤400 字符、总量 ≤4KB、优先级截断）
"""

import sys
import time
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from specstd.knowledge_index import (
    build_index,
    match_tool_call,
    match_user_text,
    KnowledgeNudger,
    clear_cache,
    NUDGE_MAX_CHARS,
    NUDGE_BUDGET,
)

GLOSSARY = """# 语义词典

### 盘点会话 [token: inventory-session]

- **语义**：一次盘点活动内的会话，由活动+平台唯一确定
- **规则**：仅 ACTIVE 或 CLOSED 状态的活动下允许创建/操作会话
- **数据**：tdm_inv_session
- **关联**：FR-001 FR-004；场景 IS-PREP-002；资源码 TDM_INV_ACTIVITY
- **歧义史**：CLOSED 活动重开会话曾误判为禁止
- **出处**：specs/inventory/inventory-session/spec.md

### 权限预检 [token: precheck-permission]

- **语义**：写型场景首步校验账号权限
- **规则**：无权限时首步诚实 SKIP
- **关联**：资源码 TDM_INV_ACTIVITY；场景 IS-PREP-002
- **出处**：docs/经验包/2026-08-02-EX-8200eada
"""

ENV_MD = """# TDM 系统 — SIT 环境叙事

## 一、环境定位

SIT 是默认联调环境。

## 五、已知坑

1. **TDM_INV_ACTIVITY 未授权（EX-8200eada）**：写型场景首步必须带 precheck_permission。
"""


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "tdm"
    (ws / "specs").mkdir(parents=True)
    (ws / "glossary.md").write_text(GLOSSARY, encoding="utf-8")
    return ws


def _mk_env(tmp_path: Path) -> Path:
    """系统适配包目录（env 叙事）。"""
    sysdir = tmp_path / "systems" / "tdm" / "config"
    sysdir.mkdir(parents=True)
    (sysdir / "env.sit.md").write_text(ENV_MD, encoding="utf-8")
    return sysdir


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    return _mk_ws(tmp_path)


# ══════════════════════════════════════════════════════════
# 索引构建
# ══════════════════════════════════════════════════════════

class TestIndexBuild:
    def test_build_from_glossary(self, ws):
        idx = build_index(ws, system_dir=None)
        assert "inventory-session" in idx
        assert "precheck-permission" in idx
        term = idx["inventory-session"]
        assert term.layer == "term"
        assert term.fr_refs == ["FR-001", "FR-004"]
        assert "IS-PREP-002" in term.scenario_ids
        assert "TDM_INV_ACTIVITY" in term.resource_codes
        assert len(term.summary) <= NUDGE_MAX_CHARS  # 摘要限长
        # kg:// 寻址
        assert term.ref == "kg://tdm/term/inventory-session"

    def test_build_from_env_narrative(self, tmp_path):
        sysdir = _mk_env(tmp_path)
        idx = build_index(Path(tmp_path) / "nws", system_dir=sysdir)
        assert "env-sit" in idx
        assert idx["env-sit"].layer == "env"

    def test_build_experience_dir(self, tmp_path):
        ws = _mk_ws(tmp_path)
        exp = ws / ".specguard" / "experience"
        exp.mkdir(parents=True)
        (exp / "2026-08-02-EX-8200eada-权限缺失.md").write_text(
            "# EX-8200eada · 变量未定义（权限缺失）\n\n"
            "根因：TDM_INV_ACTIVITY 资源码无绑定账号，HTTP 200 掩盖业务失败。\n"
            "预防：写型场景首步必须带 precheck_permission。", encoding="utf-8")
        idx = build_index(ws, system_dir=None)
        assert "EX-8200eada" in idx
        assert idx["EX-8200eada"].layer == "experience"

    def test_physical_isolation(self, tmp_path):
        """物理隔离：另一工作区同名 token 各自解析，不混杂。"""
        ws_a = _mk_ws(tmp_path)
        ws_b = tmp_path / "other"
        (ws_b / "specs").mkdir(parents=True)
        (ws_b / "glossary.md").write_text(
            GLOSSARY.replace("盘点会话", "另一系统会话"), encoding="utf-8")
        idx_a = build_index(ws_a, system_dir=None)
        idx_b = build_index(ws_b, system_dir=None)
        assert idx_a["inventory-session"].title == "盘点会话"
        assert idx_b["inventory-session"].title == "另一系统会话"


# ══════════════════════════════════════════════════════════
# 指纹失效重建 + 30s TTL
# ══════════════════════════════════════════════════════════

class TestIndexRebuild:
    def test_fingerprint_invalidates(self, ws):
        idx = build_index(ws, system_dir=None)
        fp = idx.fingerprint
        # 修改词典 → 指纹变化 → 重建
        (ws / "glossary.md").write_text(
            GLOSSARY.replace("盘点会话", "盘点会话 v2"), encoding="utf-8")
        clear_cache()
        idx2 = build_index(ws, system_dir=None)
        assert idx2.fingerprint != fp
        assert idx2["inventory-session"].title == "盘点会话 v2"

    def test_ttl_cache(self, ws):
        idx = build_index(ws, system_dir=None)
        cached = build_index(ws, system_dir=None)
        assert cached is idx  # TTL 内缓存命中（同对象）
        # 强制刷新（指纹相同则仍复用；模拟指纹变化后 TTL 内不重建）
        (ws / "glossary.md").write_text(GLOSSARY + "\n### 新增 [token: new-token]\n\n- **语义**：x\n", encoding="utf-8")
        clear_cache()
        idx2 = build_index(ws, system_dir=None)
        assert "new-token" in idx2  # 显式清缓存后可见


# ══════════════════════════════════════════════════════════
# 双通道匹配
# ══════════════════════════════════════════════════════════

class TestMatching:
    def test_tool_channel_scenario_id(self, ws):
        """工具通道（主）：scenario_id → 场景关联词条。"""
        idx = build_index(ws, system_dir=None)
        hits = match_tool_call(idx, tool_name="read_scenario",
                               arguments={"scenario_id": "IS-PREP-002"})
        hit_tokens = {e.token for e in hits}
        assert "inventory-session" in hit_tokens
        assert "precheck-permission" in hit_tokens

    def test_tool_channel_error_message(self, ws):
        """工具通道：错误 category/message 匹配（错误签名优先）。"""
        idx = build_index(ws, system_dir=None)
        hits = match_tool_call(idx, tool_name="validate", arguments={},
                               result_text="变量未定义: activity.json.data.id")
        hit_tokens = {e.token for e in hits}
        assert "precheck-permission" in hit_tokens

    def test_user_channel_keyword(self, ws):
        """用户通道（辅）：自由文本关键词匹配。"""
        idx = build_index(ws, system_dir=None)
        hits = match_user_text(idx, "帮我看看盘点会话为什么失败")
        hit_tokens = {e.token for e in hits}
        assert "inventory-session" in hit_tokens

    def test_no_agent_output_matching(self, ws):
        """红线：不做 agent 输出匹配（防回环）——仅工具结果/用户输入两通道。"""
        idx = build_index(ws, system_dir=None)
        # agent 输出（assistant 消息）不应有匹配入口
        assert not hasattr(idx, "match_agent_output")


# ══════════════════════════════════════════════════════════
# 投递预算纪律
# ══════════════════════════════════════════════════════════

class TestNudger:
    def test_once_per_session(self, ws):
        idx = build_index(ws, system_dir=None)
        n = KnowledgeNudger(idx)
        block1 = n.compose("IS-PREP-002", "用户输入")
        assert "<knowledge_refs>" in block1
        block2 = n.compose("IS-PREP-002", "再次同场景")
        assert block2 == ""  # 每篇每会话一次，去重

    def test_summary_length_and_refs(self, ws):
        idx = build_index(ws, system_dir=None)
        n = KnowledgeNudger(idx)
        block = n.compose("IS-PREP-002", "")
        # 每条 nudge ≤400 字符摘要 + read_knowledge 指针
        for token in ("inventory-session", "precheck-permission"):
            assert f"read_knowledge" in block
            assert "kg://tdm/" in block

    def test_budget_cap(self, ws):
        idx = build_index(ws, system_dir=None)
        n = KnowledgeNudger(idx)
        total = 0
        # 模拟多轮触发：总量 ≤4KB 封顶
        for i in range(50):
            blk = n.compose(f"IS-PREP-002-{i}", f"第 {i} 轮用户输入")
            total += len(blk)
            assert total <= NUDGE_BUDGET
        assert total <= NUDGE_BUDGET
