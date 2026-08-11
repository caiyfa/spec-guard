"""M4+M5 测试：内容签名 + 反哺闭环 + 飞书通知。"""

import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from feedback.ledger import FeedbackLedger
from feedback.notify import NotifyRegistry, mask_url
from specstd.signature import sign_spec_body, sign_api_yaml, detect_changes, compute_signatures


# ══════════════════════════════════════════════════════════
# 内容签名 (M4)
# ══════════════════════════════════════════════════════════

class TestSignature:
    def test_sign_spec_body(self):
        """spec.md 主体签名稳定。"""
        text = "# Module\n\n### FR-001: Test\n\nContent here."
        sig1 = sign_spec_body(text)
        sig2 = sign_spec_body(text)
        assert sig1 == sig2
        assert len(sig1) == 12

    def test_sign_spec_body_excludes_changelog(self):
        """Changelog 变化不影响签名。"""
        text1 = "# Module\n\n### FR-001: Test\n\nContent.\n\n## 十一、Changelog\n\n- v1.0\n"
        text2 = "# Module\n\n### FR-001: Test\n\nContent.\n\n## 十一、Changelog\n\n- v1.0\n- v1.1\n"
        assert sign_spec_body(text1) == sign_spec_body(text2)

    def test_sign_spec_body_detects_change(self):
        """spec 主体变化 → 签名变化。"""
        text1 = "# Module\n\n### FR-001: Test A\n"
        text2 = "# Module\n\n### FR-001: Test B\n"
        assert sign_spec_body(text1) != sign_spec_body(text2)

    def test_sign_api_yaml(self):
        """api.yaml 签名。"""
        api_spec = {
            "openapi": "3.0.3",
            "paths": {
                "/api/test": {
                    "get": {
                        "parameters": [{"name": "id"}],
                        "responses": {"200": {}, "404": {}},
                    },
                },
            },
        }
        sigs = sign_api_yaml(api_spec)
        assert "/api/test" in sigs
        assert "get" in sigs["/api/test"]
        assert len(sigs["/api/test"]["get"]) == 12

    def test_detect_changes(self):
        """检测签名变化。"""
        baseline = {
            "specs/m1/f1/spec.md": {"spec_body": "aaa", "api_paths": {}},
        }
        current = {
            "specs/m1/f1/spec.md": {"spec_body": "bbb", "api_paths": {}},
            "specs/m1/f2/spec.md": {"spec_body": "ccc", "api_paths": {}},
        }
        changes = detect_changes(current, baseline)
        assert len(changes) == 2
        types = {c["type"] for c in changes}
        assert "spec_body_changed" in types
        assert "added" in types

    def test_compute_signatures(self, tmp_path):
        """计算工作区签名。"""
        specs_dir = tmp_path / "specs" / "m1" / "f1"
        specs_dir.mkdir(parents=True)
        (specs_dir / "spec.md").write_text("# M1 F1\n\n### FR-001: Test\n", encoding="utf-8")
        sigs = compute_signatures(tmp_path)
        assert len(sigs) == 1
        key = list(sigs.keys())[0]
        assert "spec_body" in sigs[key]


# ══════════════════════════════════════════════════════════
# 反哺台账 (M5)
# ══════════════════════════════════════════════════════════

class TestFeedbackLedger:
    def test_create(self, tmp_path):
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create("测试条目", source="loop_b", scenario_id="PP-RC-001")
        assert entry["spq_id"] == "SPQ-001"
        assert entry["status"] == "pending"

    def test_transition(self, tmp_path):
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create("测试")
        updated = ledger.transition(entry["spq_id"], "in_progress")
        assert updated["status"] == "in_progress"
        assert len(updated["events"]) == 2

    def test_list_by_status(self, tmp_path):
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        ledger.create("A")
        entry = ledger.create("B")
        ledger.transition(entry["spq_id"], "closed")
        assert len(ledger.list_entries("pending")) == 1
        assert len(ledger.list_entries("closed")) == 1

    def test_persistence(self, tmp_path):
        path = tmp_path / "ledger.json"
        l1 = FeedbackLedger(path)
        l1.create("持久化")
        l2 = FeedbackLedger(path)
        assert len(l2.list_entries()) == 1

    def test_invalid_status(self, tmp_path):
        ledger = FeedbackLedger(tmp_path / "ledger.json")
        entry = ledger.create("test")
        with pytest.raises(ValueError):
            ledger.transition(entry["spq_id"], "invalid")


# ══════════════════════════════════════════════════════════
# 飞书通知 (M5)
# ══════════════════════════════════════════════════════════

class TestMaskUrl:
    def test_mask(self):
        masked = mask_url("https://open.feishu.cn/open-apis/bot/v2/hook/a3f8c21")
        assert "open.feishu.cn" in masked
        assert "***" in masked
        assert "a3f8c21" not in masked

    def test_short(self):
        masked = mask_url("https://example.com/ab")
        assert "***" in masked


class TestNotifyRegistry:
    def test_register(self, tmp_path):
        reg = NotifyRegistry(tmp_path / "registry.json")
        entry = reg.register("tdm", "PP-RC-*", "https://open.feishu.cn/hook/a3f8c21")
        assert entry["id"] == "wh-001"
        assert entry["masked_url"] != entry["url"]

    def test_list_masks_url(self, tmp_path):
        reg = NotifyRegistry(tmp_path / "registry.json")
        reg.register("tdm", "PP-*", "https://open.feishu.cn/hook/secret")
        items = reg.list_webhooks()
        assert "url" not in items[0]
        assert "masked_url" in items[0]

    def test_find_matches(self, tmp_path):
        reg = NotifyRegistry(tmp_path / "registry.json")
        reg.register("tdm", "PP-RC-*", "https://open.feishu.cn/h1", ["fail"])
        reg.register("tdm", "EV-*", "https://open.feishu.cn/h2", ["fail"])
        matches = reg.find_matches("tdm", "PP-RC-001", "fail")
        assert len(matches) == 1

    def test_no_match_wrong_system(self, tmp_path):
        reg = NotifyRegistry(tmp_path / "registry.json")
        reg.register("tdm", "PP-*", "https://open.feishu.cn/hook")
        assert len(reg.find_matches("pbs", "PP-RC-001", "fail")) == 0

    def test_unregister(self, tmp_path):
        reg = NotifyRegistry(tmp_path / "registry.json")
        entry = reg.register("tdm", "PP-*", "https://open.feishu.cn/hook")
        assert reg.unregister(entry["id"]) is True
        assert len(reg.list_webhooks()) == 0
