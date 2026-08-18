"""lark_auth 二维码授权测试（T-703 增补：对话内展示二维码+链接引导授权）。

覆盖：
- _make_qr_data_uri：合法 data URI（PNG 魔数）/ 空 url 降级 / segno 缺失降级
- do_login：waiting 分支返回 qr_data_uri；completed/error 分支不含二维码
- resolve_tools：product 角色（requirement_interview 交集）可见 lark_auth_login
全部离线：monkeypatch _run_lark，不触真实飞书。
"""

import base64
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from mcp_server.tools import lark_auth  # noqa: E402


# ══════════════════════════════════════════════════════════
# _make_qr_data_uri
# ══════════════════════════════════════════════════════════

class TestQrDataUri:
    def test_qr_data_uri_valid_png(self):
        """正常生成 base64 PNG data URI（PNG 魔数 \x89PNG 开头）。"""
        uri = lark_auth._make_qr_data_uri("https://example.com/auth")
        assert uri.startswith("data:image/png;base64,")
        raw = base64.b64decode(uri.split(",", 1)[1])
        assert raw[:4] == b"\x89PNG"

    def test_qr_data_uri_empty_url(self):
        """空 url 返回空串（降级）。"""
        assert lark_auth._make_qr_data_uri("") == ""

    def test_qr_data_uri_segno_missing(self, monkeypatch):
        """segno 缺失时降级为空串，不抛异常。"""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "segno":
                raise ImportError("No module named 'segno'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert lark_auth._make_qr_data_uri("https://example.com/auth") == ""


# ══════════════════════════════════════════════════════════
# do_login（二维码 + 链接双返回）
# ══════════════════════════════════════════════════════════

class TestEnsureConfig:
    def test_copies_home_config_when_missing(self, tmp_path, monkeypatch):
        """隔离目录缺 config.json → 从本机配置复制（用户零手动配置）。"""
        home = tmp_path / "home"
        (home / ".lark-cli").mkdir(parents=True)
        (home / ".lark-cli" / "config.json").write_text(
            '{"appId": "cli_test", "brand": "feishu"}', encoding="utf-8")
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setattr(lark_auth, "_LARK_DIR", tmp_path / "isolated")
        lark_auth._ensure_config("90024166")
        dest = tmp_path / "isolated" / "90024166" / ".lark-cli" / "config.json"
        assert dest.is_file()
        assert "cli_test" in dest.read_text(encoding="utf-8")

    def test_skips_when_config_exists(self, tmp_path, monkeypatch):
        """隔离目录已有 config.json → 不覆盖。"""
        isolated = tmp_path / "isolated"
        dest = isolated / "90024166" / ".lark-cli" / "config.json"
        dest.parent.mkdir(parents=True)
        dest.write_text('{"appId": "cli_existing"}', encoding="utf-8")
        monkeypatch.setattr(lark_auth, "_LARK_DIR", isolated)
        home = tmp_path / "home"
        (home / ".lark-cli").mkdir(parents=True)
        (home / ".lark-cli" / "config.json").write_text(
            '{"appId": "cli_home"}', encoding="utf-8")
        monkeypatch.setenv("USERPROFILE", str(home))
        lark_auth._ensure_config("90024166")
        assert dest.read_text(encoding="utf-8") == '{"appId": "cli_existing"}'

    def test_skips_when_no_home_config(self, tmp_path, monkeypatch):
        """本机也无配置 → 静默跳过（auth login 返回可读错误引导）。"""
        monkeypatch.setattr(lark_auth, "_LARK_DIR", tmp_path / "isolated")
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "empty_home"))
        lark_auth._ensure_config("90024166")  # 不抛异常即可
        assert not (tmp_path / "isolated" / "90024166" / ".lark-cli" / "config.json").exists()


class TestDoLogin:
    def test_waiting_uses_json_flag(self, monkeypatch):
        """auth login 走 --no-wait --json（auth 域不支持 --format json）。"""
        captured = {}

        def fake(emp_no, args, timeout=90, json_output=True):
            captured["args"] = list(args)
            captured["json_output"] = json_output
            return {"ok": True, "data": {
                "verification_url": "https://feishu.cn/oauth?code=abc",
                "device_code": "dev-1",
            }}

        monkeypatch.setattr(lark_auth, "_run_lark", fake)
        result = lark_auth.do_login("90024166")
        assert result["phase"] == "waiting"
        assert "--no-wait" in captured["args"] and "--json" in captured["args"]
        assert "--format" not in captured["args"]
        assert captured["json_output"] is False
        assert result["verification_url"] == "https://feishu.cn/oauth?code=abc"
        assert result["qr_data_uri"].startswith("data:image/png;base64,")

    def test_error_branch_no_qr(self, monkeypatch):
        """error 分支不含二维码字段。"""
        monkeypatch.setattr(lark_auth, "_run_lark",
                            lambda *a, **k: (_ for _ in ()).throw(
                                ValueError("lark-cli 调用失败")))
        result = lark_auth.do_login("90024166")
        assert result["phase"] == "error"
        assert "qr_data_uri" not in result


class TestDoLoginComplete:
    def test_complete_ok(self, monkeypatch):
        """device-code 收尾成功：--device-code + --json，返回 completed。"""
        captured = {}

        def fake(emp_no, args, timeout=90, json_output=True):
            captured["args"] = list(args)
            captured["timeout"] = timeout
            captured["json_output"] = json_output
            return {"ok": True, "data": {}}

        def fake_status(emp_no):
            return {"bound": True, "identity": "user",
                    "identity_name": "蔡云飞", "open_id": "ou_x"}

        monkeypatch.setattr(lark_auth, "_run_lark", fake)
        monkeypatch.setattr(lark_auth, "do_status", fake_status)
        result = lark_auth.do_login_complete("90024166", "dev-1")
        assert result["phase"] == "completed"
        assert "--device-code" in captured["args"]
        assert "--json" in captured["args"] and "--format" not in captured["args"]
        assert captured["json_output"] is False

    def test_complete_timeout_is_pending(self, monkeypatch):
        """CLI 轮询超时（用户未扫码）→ pending，可重试。"""
        monkeypatch.setattr(lark_auth, "_run_lark",
                            lambda *a, **k: (_ for _ in ()).throw(
                                ValueError("lark-cli 调用超时（>15s）")))
        result = lark_auth.do_login_complete("90024166", "dev-1")
        assert result["phase"] == "pending"

    def test_complete_empty_code(self):
        """device_code 为空 → error。"""
        result = lark_auth.do_login_complete("90024166", "")
        assert result["phase"] == "error"


# ══════════════════════════════════════════════════════════
# RBAC/purpose 白名单可见性
# ══════════════════════════════════════════════════════════

class TestWhitelist:
    def test_product_can_call_login(self):
        """product 角色 ∩ requirement_interview：lark_auth_login 可见（对话内可发起授权）。"""
        from agent.purpose_loader import load_purpose
        from agent.runtime import resolve_tools

        pdef = load_purpose("requirement_interview")
        tools = resolve_tools(purpose_tools=list(pdef.tools), user_roles=["product"])
        names = {t.name for t in tools}
        assert "lark_auth_login" in names
        assert "lark_auth_status" in names
        assert "lark_execute" in names


# ══════════════════════════════════════════════════════════
# T-943：status 真实结构解析 + 必需 scope 缺失 + 审核中判定
# 实测定案：auth status 输出 identities.user.scope 为空格分隔字符串
# （旧代码读不存在的 data.scopes 数组→bound=true 但身份/scopes 恒空）。
# 审核态识别：刚授权（30 分钟内）+ 必需 scope 仍缺失 → 审核中。
# ══════════════════════════════════════════════════════════

_AUTH_STATUS_PAYLOAD = {
    "identities": {
        "bot": {"status": "ready", "available": True},
        "user": {
            "status": "ready", "available": True,
            "openId": "ou_x", "userName": "蔡云飞",
            "tokenStatus": "valid",
            "scope": "im:chat:read docs:document.content:read search:docs:read",
        },
    },
}


class TestStatusParseAndReviewing:
    def _mk_user(self, tmp_path, monkeypatch, emp="u1"):
        monkeypatch.setattr(lark_auth, "_LARK_DIR", tmp_path)
        d = tmp_path / emp
        d.mkdir(parents=True, exist_ok=True)
        (d / "token.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(lark_auth, "_run_lark",
                            lambda e, a, **kw: _AUTH_STATUS_PAYLOAD)

    def test_status_parses_real_structure(self, tmp_path, monkeypatch):
        """真实结构 identities.user（scope 空格分隔）→ 身份/scopes 数组正确。"""
        self._mk_user(tmp_path, monkeypatch)
        st = lark_auth.do_status("u1")
        assert st["bound"] is True
        assert st["identity"] == "user"
        assert st["identity_name"] == "蔡云飞"
        assert st["open_id"] == "ou_x"
        assert "im:chat:read" in st["scopes"]

    def test_status_missing_and_reviewing(self, tmp_path, monkeypatch):
        """缺 contactuser:search 等 → missing_scopes；刚授权 → reviewing=True（审核中）。"""
        self._mk_user(tmp_path, monkeypatch)
        lark_auth._mark_auth_done("u1")          # 刚授权完成（写 last_auth）
        st = lark_auth.do_status("u1")
        assert "contactuser:search" in st["missing_scopes"]
        assert "minutes:minutes.search:read" in st["missing_scopes"]
        assert st["reviewing"] is True

    def test_status_missing_without_recent_auth(self, tmp_path, monkeypatch):
        """无近期授权 + 缺失 → reviewing=False（未授权全，非审核）。"""
        self._mk_user(tmp_path, monkeypatch)
        st = lark_auth.do_status("u1")
        assert st["missing_scopes"] and st["reviewing"] is False

    def test_status_all_required_present(self, tmp_path, monkeypatch):
        """全量必需 scope → missing_scopes 空、reviewing=False。"""
        payload = {"identities": {"user": {
            "status": "ready", "available": True, "openId": "ou_x",
            "userName": "n", "tokenStatus": "valid",
            "scope": " ".join(lark_auth._REQUIRED_SCOPES)}}}
        monkeypatch.setattr(lark_auth, "_LARK_DIR", tmp_path)
        d = tmp_path / "u1"
        d.mkdir(parents=True)
        (d / "token.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(lark_auth, "_run_lark", lambda e, a, **kw: payload)
        st = lark_auth.do_status("u1")
        assert st["missing_scopes"] == [] and st["reviewing"] is False
