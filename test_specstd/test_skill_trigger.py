"""skill_loader 技能确定性触发测试（K-xxx：关键词 → 技能提示映射）。

覆盖：keywords frontmatter 解析（数组/逗号字符串）、match_skills_hint 命中与
不命中、多技能命中、runtime 注入（新会话 + 恢复会话）、全技能 keywords 完备性。
"""

from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent

from agent import skill_loader  # noqa: E402


class TestKeywordsParsing:
    def test_list_keywords_array(self):
        """frontmatter keywords 数组解析。"""
        s = skill_loader.load_skill("generate-scenario")
        assert s is not None
        assert "生成" in s.keywords and "新场景" in s.keywords

    def test_parse_comma_string_compat(self):
        """兼容逗号分隔字符串形式（_parse_skill_file 直接测）。"""
        text = """---
name: demo
description: 测试用描述
keywords: 甲, 乙,丙
---
正文
"""
        s = skill_loader._parse_skill_file("demo", text)
        assert s.keywords == ["甲", "乙", "丙"]

    def test_all_skills_have_keywords(self):
        """全部技能文件必须声明非空 keywords（新增技能漏加会被拦）。"""
        skills = skill_loader.list_skills()
        assert len(skills) >= 4
        for s in skills:
            assert s.keywords, f"技能 {s.name} 缺少 keywords（确定性触发依赖它）"


class TestMatchSkillsHint:
    def test_hit_generate(self):
        hint = skill_loader.match_skills_hint("帮我生成 PP-RC-009 场景")
        assert "generate-scenario" in hint and "技能提示" in hint

    def test_hit_debug(self):
        hint = skill_loader.match_skills_hint("EX-12345678 这个测试为什么失败？")
        assert "debug-failure" in hint

    def test_hit_validate(self):
        hint = skill_loader.match_skills_hint("帮我 validate 一下这个草稿能入库吗")
        assert "validate-conformance" in hint

    def test_no_hit(self):
        assert skill_loader.match_skills_hint("你好，介绍一下你自己") == ""
        assert skill_loader.match_skills_hint("") == ""

    def test_multiple_hits(self):
        """多技能命中时全部列出（如「校验失败」同时命中 validate/debug）。"""
        hint = skill_loader.match_skills_hint("校验一下这个场景为什么校验失败")
        assert "validate-conformance" in hint and "debug-failure" in hint


class TestRuntimeInjection:
    """runtime 注入验证（MockLLM 复刻 test_agent 的最小实现）。"""

    class MockLLM:
        def __init__(self):
            self._n = 0
            self._total_tokens = 0
            self.max_context_tokens = 0

        @property
        def is_mock(self):
            return True

        def chat(self, messages, tools=None, temperature=0.7, on_delta=None):
            self._n += 1
            self._total_tokens += 15
            return {"role": "assistant", "content": "好"}, \
                {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

        def set_metrics_file(self, path):
            pass

        def get_stats(self):
            return {"total_tokens": self._total_tokens, "is_mock": True, "model": "mock"}

    def _run(self, msg):
        from agent.runtime import AgentRuntime
        rt = AgentRuntime(self.MockLLM(), max_turns=1)
        return rt.run("sys", msg)

    def test_inject_on_new_session(self):
        """新会话：用户消息命中关键词 → system 提示注入在 user 消息前。"""
        msgs = self._run("帮我生成 PP-RC-009 场景")
        roles = [m["role"] for m in msgs]
        assert roles.count("system") == 2  # 主 prompt + 技能提示
        assert any("generate-scenario" in m.get("content", "") for m in msgs if m["role"] == "system")
        # 提示位于 user 消息之前
        sys_idx = [i for i, m in enumerate(msgs) if m["role"] == "system" and "generate-scenario" in m["content"]][0]
        user_idx = [i for i, m in enumerate(msgs) if m["role"] == "user"][0]
        assert sys_idx < user_idx

    def test_no_inject_without_match(self):
        msgs = self._run("今天天气怎么样")
        assert sum(1 for m in msgs if m["role"] == "system") == 1  # 只有主 prompt
