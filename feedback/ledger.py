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

    VALID_STATUSES = ["pending", "in_progress", "zentao_filed", "closed"]
    VALID_SOURCES = ["loop_a", "loop_b"]
    # H-1: 漏洞条目扩展
    VALID_VTYPES = ["logic_defect", "spec_impl_mismatch", "missing_info", "behavior_deviation"]
    VALID_SEVERITIES = ["blocker", "major", "minor"]
    # V15 修复：合法状态流转（closed 为终态，不可重开）
    # M06 §4.3：zentao_filed = 已提禅道 BUG（挂 sf_external_refs 双向链接），
    # 禅道修复后回归：PASS → closed，FAIL → 回 in_progress + 通知
    ALLOWED_TRANSITIONS = {
        "pending": {"in_progress", "zentao_filed", "closed"},
        "in_progress": {"pending", "zentao_filed", "closed"},
        "zentao_filed": {"in_progress", "closed"},
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

    # ══════════════════════════════════════════════════════════
    # H-1: 漏洞条目扩展
    # ══════════════════════════════════════════════════════════

    def create_vulnerability(
        self,
        vtype: str,
        severity: str,
        location: str,
        summary: str,
        evidence: str = "",
        suggestion: str = "",
        scenario_id: str = "",
    ) -> dict:
        """创建漏洞台账条目（H-1 扩展）。

        漏洞条目在普通条目基础上增加 vtype / severity / location /
        evidence / suggestion 字段，source 固定为 loop_b（审计发现）。

        Args:
            vtype: 漏洞类型（logic_defect / spec_impl_mismatch /
                   missing_info / behavior_deviation）
            severity: 严重度（blocker / major / minor）
            location: FR ID 或文件路径
            summary: 一句话描述
            evidence: 证据（spec 原文 / 接口返回）
            suggestion: 建议修正
            scenario_id: 关联场景 ID（可选）

        Returns:
            创建的台账条目
        """
        if vtype not in self.VALID_VTYPES:
            raise ValueError(f"vtype 必须为 {self.VALID_VTYPES}")
        if severity not in self.VALID_SEVERITIES:
            raise ValueError(f"severity 必须为 {self.VALID_SEVERITIES}")
        now = datetime.now().isoformat(timespec="seconds")
        entry = {
            "spq_id": self._next_id(),
            "title": summary,
            "source": "loop_b",
            "status": "pending",
            "scenario_id": scenario_id,
            "detail": "",
            # 漏洞专属字段
            "vtype": vtype,
            "severity": severity,
            "location": location,
            "summary": summary,
            "evidence": evidence,
            "suggestion": suggestion,
            "created_at": now,
            "updated_at": now,
            "events": [{"type": "created", "timestamp": now}],
        }
        self._entries.append(entry)
        self._save()
        return entry

    def list_vulnerabilities(self, status: str = None) -> list[dict]:
        """列出漏洞条目（含 vtype 字段的条目）。

        Args:
            status: 按状态过滤（可选）
        """
        result = [e for e in self._entries if "vtype" in e]
        if status:
            result = [e for e in result if e["status"] == status]
        return result

    def count_vulnerabilities(self, status: str = "pending") -> int:
        """统计漏洞条目数量（按状态）。

        供 H-2 路由器查询 pending 漏洞数。
        """
        return sum(1 for e in self._entries if "vtype" in e and e["status"] == status)

    # ══════════════════════════════════════════════════════════
    # H-5: 闭环衔接便捷方法
    # ══════════════════════════════════════════════════════════

    def close_vulnerability(self, spq_id: str, note: str = "") -> dict:
        """便捷方法：关闭漏洞（pending/in_progress → closed）。

        Agent 重新审计后发现漏洞已修正时调用。

        Args:
            spq_id: 漏洞条目 ID
            note: 关闭备注（可选，如「重新审计确认已修正」）
        """
        entry = self.transition(spq_id, "closed")
        if note:
            entry.setdefault("events", []).append({
                "type": "closed",
                "note": note,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            })
            self._save()
        return entry

    def close_vulnerabilities_by_location(self, location: str) -> list[dict]:
        """按位置批量关闭漏洞。

        Agent 重新审计后某 FR/文件路径的漏洞已全部修正时调用。
        只关闭非 closed 状态的漏洞。

        Args:
            location: FR ID 或文件路径

        Returns:
            被关闭的漏洞列表
        """
        closed = []
        for entry in self._entries:
            if ("vtype" in entry
                    and entry.get("location") == location
                    and entry["status"] != "closed"):
                self.transition(entry["spq_id"], "closed")
                closed.append(entry)
        return closed

    def get_vulnerability_summary(self) -> dict:
        """漏洞统计摘要（供前端展示和路由信号）。

        Returns:
            {total, pending, in_progress, closed}
        """
        vulns = [e for e in self._entries if "vtype" in e]
        return {
            "total": len(vulns),
            "pending": sum(1 for v in vulns if v["status"] == "pending"),
            "in_progress": sum(1 for v in vulns if v["status"] == "in_progress"),
            "closed": sum(1 for v in vulns if v["status"] == "closed"),
        }
