"""T-971 system 一等公民化——resolve_system 唯一解析口径。

优先级：显式参数 > 当前工作区 system（contextvar/SG_WORKSPACE/注册表 active）
> SPEC_GUARD_SYSTEM 环境变量 > "tdm"。此前该口径散落 9+ 处各自解析，
多系统部署下锁死单系统（架构反馈第二轮第 2 点断链清单）。
"""

import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

import specstd.workspace as wsm  # noqa: E402
from specstd.workspace import (  # noqa: E402
    reset_context_workspace,
    resolve_system,
    set_context_workspace,
)


def _setup_ws(tmp_path, monkeypatch, name, system, activate=True):
    """隔离注册表并注册一个工作区（复用 test_specguard_dir 手法）。"""
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    ws = tmp_path / name
    ws.mkdir(parents=True, exist_ok=True)
    return wsm.register_local(name, str(ws), system, activate=activate)


class TestResolveSystem:
    def test_explicit_param_wins(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        assert resolve_system("hr") == "hr"

    def test_workspace_system(self, tmp_path, monkeypatch):
        _setup_ws(tmp_path, monkeypatch, "w1", "hr")
        assert resolve_system() == "hr"

    def test_workspace_via_contextvar(self, tmp_path, monkeypatch):
        _setup_ws(tmp_path, monkeypatch, "w1", "tdm", activate=False)
        _setup_ws(tmp_path, monkeypatch, "w2", "ehr", activate=True)
        token = set_context_workspace("w1")
        try:
            assert resolve_system() == "tdm"  # contextvar 优先于注册表 active
        finally:
            reset_context_workspace(token)

    def test_env_var_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        monkeypatch.setenv("SPEC_GUARD_SYSTEM", "crm")
        assert resolve_system() == "crm"

    def test_default_tdm(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        monkeypatch.delenv("SPEC_GUARD_SYSTEM", raising=False)
        assert resolve_system() == "tdm"

    def test_workspace_without_system_falls_to_env(self, tmp_path, monkeypatch):
        # 注册表行 system 为空（旧数据）→ 不阻断，落环境变量口径
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        monkeypatch.setenv("SPEC_GUARD_SYSTEM", "crm")
        ws = tmp_path / "legacy"
        ws.mkdir()
        wsm.register_local("legacy", str(ws), "", activate=True)
        assert resolve_system() == "crm"
