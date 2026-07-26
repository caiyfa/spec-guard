"""agent.session — JSONL 会话持久化。

kill 后重跑可从 JSONL 续会话：每条消息一行 JSON，append-only。
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


class SessionManager:
    """JSONL 会话持久化管理器。"""

    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create(self) -> str:
        """创建新会话，返回 session_id。"""
        return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    def save(self, session_id: str, messages: list[dict], metrics: dict = None):
        """保存会话到 JSONL（覆盖写，每次全量保存）。"""
        path = self.sessions_dir / f"{session_id}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            if metrics:
                f.write(json.dumps({"_type": "metrics", **metrics}, ensure_ascii=False) + "\n")

    def append(self, session_id: str, message: dict):
        """追加单条消息到 JSONL。"""
        path = self.sessions_dir / f"{session_id}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def load(self, session_id: str) -> Optional[list[dict]]:
        """从 JSONL 加载会话消息列表。"""
        path = self.sessions_dir / f"{session_id}.jsonl"
        if not path.is_file():
            return None
        messages = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("_type") == "metrics":
                    continue  # 跳过计量行
                messages.append(msg)
        return messages

    def list_sessions(self) -> list[dict]:
        """列出所有会话。"""
        sessions = []
        for f in sorted(self.sessions_dir.glob("*.jsonl"), reverse=True):
            stat = f.stat()
            sessions.append({
                "id": f.stem,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            })
        return sessions

    def resume(self, session_id: str) -> Optional[list[dict]]:
        """恢复会话（等同于 load）。"""
        return self.load(session_id)
