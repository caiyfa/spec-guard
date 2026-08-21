"""M4+M5 测试：内容签名 + 反哺闭环 + 群聊通知（T-996：webhook 存储统一 notify_config）。"""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from feedback.ledger import FeedbackLedger
from feedback import notify as notify_mod
from feedback.notify import mask_url
from specstd.signature import sign_spec_body, sign_api_yaml, detect_changes, compute_signatures


@pytest.fixture
def cfg_store(tmp_path, monkeypatch):
    """notify_config 指向临时库（隔离，不碰 workbench.db）。"""
    import sg_core.notify_config as nc
    db = tmp_path / "notify.db"

    def connect():
        conn = sqlite3.connect(str(db), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(nc, "db_connect", connect)
    monkeypatch.setattr(nc, "init_db", lambda: None)
    return nc


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


class TestCaseNotify:
    """T-996 二合一：用例级通知走统一 notify_configs（system + scenario_pattern + event 过滤）。"""

    def _mk(self, nc, system="tdm", pattern="PP-*", events=("fail",), **kw):
        return nc.create_config({
            "name": f"{system}/{pattern}", "channel": "feishu",
            "webhook_url": "https://open.feishu.cn/hook/a3f8c21",
            "events": list(events), "system": system, "scenario_pattern": pattern, **kw,
        })

    def test_create_keeps_case_filters(self, cfg_store):
        cfg = self._mk(cfg_store, pattern="PP-RC-*")
        assert cfg["system"] == "tdm"
        assert cfg["scenario_pattern"] == "PP-RC-*"
        assert cfg["events"] == ["fail"]

    def test_list_masks_url(self, cfg_store):
        self._mk(cfg_store)
        items = cfg_store.list_configs()
        assert "***" in items[0]["webhook_url"]
        assert "a3f8c21" not in items[0]["webhook_url"]

    def test_case_event_match_and_receipt(self, cfg_store, tmp_path, monkeypatch):
        self._mk(cfg_store, pattern="PP-RC-*")
        self._mk(cfg_store, pattern="EV-*")
        sent = []

        async def fake_send(cfg, event, payload):
            sent.append((cfg["id"], event, payload))
            return True

        receipts = tmp_path / "receipts.jsonl"
        monkeypatch.setattr(notify_mod, "send_notification", fake_send)
        monkeypatch.setattr(notify_mod, "RECEIPTS_PATH", receipts)
        results = asyncio.run(notify_mod.notify_case_event(
            "tdm", "PP-RC-001", "fail", "FAIL", "断言失败", "reports/X/report.md"))
        assert len(results) == 1 and results[0]["ok"] is True
        assert sent[0][2]["scenario_id"] == "PP-RC-001"
        receipt = json.loads(receipts.read_text(encoding="utf-8").splitlines()[0])
        assert receipt["matched"] == 1 and receipt["event"] == "fail"

    def test_no_match_wrong_system(self, cfg_store, tmp_path, monkeypatch):
        self._mk(cfg_store, system="tdm")
        monkeypatch.setattr(notify_mod, "RECEIPTS_PATH", tmp_path / "receipts.jsonl")
        results = asyncio.run(notify_mod.notify_case_event("pbs", "PP-RC-001", "fail", "FAIL", "x"))
        assert results == []

    def test_event_not_subscribed(self, cfg_store, tmp_path, monkeypatch):
        self._mk(cfg_store, events=("fail",))
        monkeypatch.setattr(notify_mod, "RECEIPTS_PATH", tmp_path / "receipts.jsonl")
        results = asyncio.run(notify_mod.notify_case_event("tdm", "PP-001", "drift", "DRIFT", "x"))
        assert results == []

    def test_migrate_registry_to_configs(self, cfg_store, tmp_path, monkeypatch):
        root = tmp_path / "sgroot"
        (root / "feedback").mkdir(parents=True)
        (root / "feedback" / "registry.json").write_text(json.dumps([
            {"id": "wh-001", "system": "tdm", "scenario_pattern": "PP-*",
             "url": "https://open.feishu.cn/hook/abc", "events": ["fail", "drift"],
             "created_at": "2026-08-01T00:00:00"},
            {"id": "wh-002", "system": "tdm", "scenario_pattern": "*",
             "url": "http://10.0.0.1/hook", "events": ["skip"],  # SSRF 不过，跳过
             "created_at": "2026-08-01T00:00:00"},
        ]), encoding="utf-8")
        monkeypatch.setattr(notify_mod, "RECEIPTS_PATH", tmp_path / "receipts.jsonl")
        n = notify_mod.migrate_registry_to_configs(root)
        assert n == 1
        configs = cfg_store.list_configs()
        assert len(configs) == 1
        assert configs[0]["system"] == "tdm" and configs[0]["scenario_pattern"] == "PP-*"
        assert set(configs[0]["events"]) == {"fail", "drift"}
        # 幂等：registry.json 已改名 .migrated，再次调用返回 0
        assert not (root / "feedback" / "registry.json").exists()
        assert (root / "feedback" / "registry.json.migrated").is_file()
        assert notify_mod.migrate_registry_to_configs(root) == 0
