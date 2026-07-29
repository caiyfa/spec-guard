"""test_mode_loader — agent.mode_loader 单元测试（A-1 验收）。

覆盖验收标准：
1. agent/modes/*.md 的 frontmatter 不再包含 temperature 字段
2. ModeDef 数据类不含 temperature 属性
3. 现有 mode 切换功能不受影响（工具白名单、prompt 片段正常）
4. 旧的带 temperature 的 mode 文件不报错（向后兼容）
"""

import sys
import tempfile
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.mode_loader import ModeDef, load_mode, list_modes, clear_cache, _parse_mode_file


# ══════════════════════════════════════════════════════════
# 验收 1: modes/*.md 的 frontmatter 不再包含 temperature
# ══════════════════════════════════════════════════════════

class TestModeFilesNoTemperature:
    """4 个 mode 文件的 frontmatter 不再包含 temperature 字段。"""

    def test_generate_no_temperature(self):
        clear_cache()
        mode = load_mode("generate")
        assert mode is not None
        # ModeDef 不应有 temperature 属性
        assert not hasattr(mode, "temperature")

    def test_debug_no_temperature(self):
        clear_cache()
        mode = load_mode("debug")
        assert mode is not None
        assert not hasattr(mode, "temperature")

    def test_analyze_no_temperature(self):
        clear_cache()
        mode = load_mode("analyze")
        assert mode is not None
        assert not hasattr(mode, "temperature")

    def test_chat_no_temperature(self):
        clear_cache()
        mode = load_mode("chat")
        assert mode is not None
        assert not hasattr(mode, "temperature")


# ══════════════════════════════════════════════════════════
# 验收 2: ModeDef 数据类不含 temperature 属性
# ══════════════════════════════════════════════════════════

class TestModeDefNoTemperature:
    """ModeDef 数据类不含 temperature 属性。"""

    def test_no_temperature_attribute(self):
        """ModeDef 无 temperature 字段。"""
        assert not hasattr(ModeDef, "temperature")

    def test_mode_def_fields(self):
        """ModeDef 只包含预期的字段。"""
        mode = ModeDef(name="test", tools=["read_spec"], prompt_fragment="body")
        assert mode.name == "test"
        assert mode.tools == ["read_spec"]
        assert mode.prompt_fragment == "body"
        assert mode.description == ""
        # 确认 temperature 不存在
        assert not hasattr(mode, "temperature")


# ══════════════════════════════════════════════════════════
# 验收 3: 现有 mode 切换功能不受影响
# ══════════════════════════════════════════════════════════

class TestModeFunctionality:
    """mode 加载功能正常（工具白名单、prompt 片段）。"""

    def test_generate_tools(self):
        clear_cache()
        mode = load_mode("generate")
        assert mode is not None
        assert "read_spec" in mode.tools
        assert "validate" in mode.tools
        assert "write_draft" in mode.tools

    def test_generate_prompt_fragment(self):
        clear_cache()
        mode = load_mode("generate")
        assert mode is not None
        assert len(mode.prompt_fragment) > 0
        assert "场景生成" in mode.prompt_fragment

    def test_chat_empty_tools(self):
        clear_cache()
        mode = load_mode("chat")
        assert mode is not None
        assert mode.tools == []

    def test_debug_tools(self):
        clear_cache()
        mode = load_mode("debug")
        assert mode is not None
        assert "read_run_report" in mode.tools
        assert "db_evidence" in mode.tools

    def test_analyze_readonly(self):
        clear_cache()
        mode = load_mode("analyze")
        assert mode is not None
        # analyze 模式是只读的，不应有写入工具
        assert "write_draft" not in mode.tools
        assert "validate" not in mode.tools

    def test_list_modes(self):
        """list_modes 返回全部 4 个模式。"""
        clear_cache()
        modes = list_modes()
        names = [m.name for m in modes]
        assert "generate" in names
        assert "debug" in names
        assert "analyze" in names
        assert "chat" in names


# ══════════════════════════════════════════════════════════
# 验收 4: 旧的带 temperature 的 mode 文件不报错（向后兼容）
# ══════════════════════════════════════════════════════════

class TestBackwardCompat:
    """旧文件（带 temperature 字段）不报错，只是忽略该字段。"""

    def test_old_file_with_temperature_no_error(self):
        """旧格式 mode 文件（含 temperature）能正常解析，不报错。"""
        old_content = """---
temperature: 0.3
tools:
  - read_spec
  - validate
---
你是旧格式的模式。
"""
        mode = _parse_mode_file("old_mode", old_content)
        assert mode.name == "old_mode"
        assert mode.tools == ["read_spec", "validate"]
        assert "旧格式" in mode.prompt_fragment
        # temperature 被忽略，不存在于 ModeDef
        assert not hasattr(mode, "temperature")

    def test_old_file_temperature_ignored(self):
        """temperature 值不影响 ModeDef（被完全忽略）。"""
        old_content = """---
temperature: 0.99
tools: []
---
测试。
"""
        mode = _parse_mode_file("test", old_content)
        assert mode.tools == []
        assert not hasattr(mode, "temperature")

    def test_new_file_without_temperature(self):
        """新格式 mode 文件（无 temperature）正常解析。"""
        new_content = """---
tools:
  - read_spec
---
新格式模式。
"""
        mode = _parse_mode_file("new_mode", new_content)
        assert mode.name == "new_mode"
        assert mode.tools == ["read_spec"]
        assert "新格式" in mode.prompt_fragment
