"""feedback.ledger — 反哺报告台账（SPQ 编号 + 状态机）。

状态机：pending（待讨论） → in_progress（研发修改中） → closed（已闭环）。
循环 A/B 事件自动生成台账条目。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class FeedbackLedger:
    """反哺报告台账。"""

    VALID_STATUSES = ["pending", "in_progress", "closed"]
    VALID_SOURCES = ["loop_a", "loop_b"]
    # V15 修复：合法状态流转（closed 为终态，不可重开）
    ALLOWED_TRANSITIONS = {
        "pending": {"in_progress", "closed"},
        "in_progress": {"pending", "closed"},
        "closed": set(),
    }

    def __init__(self, ledger_path: Path):
        self.path = ledger_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries = self._load()

    def _load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    def _next_id(self) -> str:
        max_num = 0
        for entry in self._entries:
            spq_id = entry.get("spq_id", "")
            if spq_id.startswith("SPQ-"):
                try:
                    num = int(spq_id[4:])
                    max_num = max(max_num, num)
                except ValueError:
                    pass
        return f"SPQ-{max_num + 1:03d}"

    def create(self, title: str, source: str = "loop_b",
               scenario_id: str = "", detail: str = "") -> dict:
        """创建台账条目。"""
        if source not in self.VALID_SOURCES:
            raise ValueError(f"source 必须为 {self.VALID_SOURCES}")
        now = datetime.now().isoformat(timespec="seconds")
        entry = {
            "spq_id": self._next_id(),
            "title": title,
            "source": source,
            "status": "pending",
            "scenario_id": scenario_id,
            "detail": detail,
            "created_at": now,
            "updated_at": now,
            "events": [{"type": "created", "timestamp": now}],
        }
        self._entries.append(entry)
        self._save()
        return entry

    def transition(self, spq_id: str, new_status: str) -> dict:
        """状态流转（仅允许合法迁移，closed 为终态）。"""
        if new_status not in self.VALID_STATUSES:
            raise ValueError(f"status 必须为 {self.VALID_STATUSES}")
        for entry in self._entries:
            if entry["spq_id"] == spq_id:
                old = entry["status"]
                if new_status == old:
                    return entry
                if new_status not in self.ALLOWED_TRANSITIONS.get(old, set()):
                    raise ValueError(
                        f"非法状态流转: {old} → {new_status}"
                        f"（允许: {sorted(self.ALLOWED_TRANSITIONS.get(old, set())) or '无（终态）'}）")
                entry["status"] = new_status
                entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
                entry["events"].append({
                    "type": "status_changed", "from": old, "to": new_status,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                })
                self._save()
                return entry
        raise KeyError(f"台账条目不存在: {spq_id}")

    def list_entries(self, status: str = None) -> list[dict]:
        """列出台账条目。"""
        if status:
            return [e for e in self._entries if e["status"] == status]
        return self._entries

    def get(self, spq_id: str) -> Optional[dict]:
        """获取单个台账条目。"""
        for entry in self._entries:
            if entry["spq_id"] == spq_id:
                return entry
        return None
