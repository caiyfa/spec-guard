"""agent.session — JSONL 会话持久化（支持工作区隔离 + 元数据）。

kill 后重跑可从 JSONL 续会话：每条消息一行 JSON，append-only。
会话路径：agent/sessions/{emp_no}/{workspace}/{session_id}.jsonl
兼容旧格式：agent/sessions/{emp_no}/{session_id}.jsonl
"""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# V11 修复：session_id 白名单（时间戳_uuidhex 格式），防路径穿越写
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _validate_session_id(session_id: str):
    """session_id 非法时抛 ValueError（防拼路径穿越）。"""
    if not session_id or not SESSION_ID_RE.match(session_id):
        raise ValueError(f"非法 session_id: {session_id!r}")


def _validate_workspace(workspace: str):
    """workspace 名称非法时抛 ValueError。"""
    if workspace and not WORKSPACE_RE.match(workspace):
        raise ValueError(f"非法 workspace: {workspace!r}")


class SessionManager:
    """JSONL 会话持久化管理器（支持工作区子目录 + 元数据）。"""

    def __init__(self, sessions_dir: Path, workspace: str = ""):
        """初始化，workspace 非空时会话存到 sessions_dir/{workspace}/。"""
        if workspace:
            _validate_workspace(workspace)
            self.sessions_dir = sessions_dir / workspace
        else:
            self.sessions_dir = sessions_dir
        self.workspace = workspace
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create(self, emp_no: str = "", workspace: str = "") -> str:
        """创建新会话，返回 session_id。首行写入元数据。"""
        sid = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        # 写元数据首行
        meta = {
            "_type": "session_meta",
            "session_id": sid,
            "emp_no": emp_no or "",
            "workspace": workspace or self.workspace or "",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "title": "",  # G4: LLM 自动生成的标题
        }
        path = self.sessions_dir / f"{sid}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        return sid

    def update_title(self, session_id: str, title: str):
        """更新会话标题（修改 JSONL 首行元数据）。"""
        _validate_session_id(session_id)
        path = self.sessions_dir / f"{session_id}.jsonl"
        if not path.is_file():
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return
        try:
            meta = json.loads(lines[0])
            if meta.get("_type") == "session_meta":
                meta["title"] = title[:50]  # 限制标题长度
                lines[0] = json.dumps(meta, ensure_ascii=False)
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except (json.JSONDecodeError, IndexError):
            pass

    def save(self, session_id: str, messages: list[dict], metrics: dict = None,
             todos: list[dict] = None, emp_no: str = "", workspace: str = ""):
        """保存会话到 JSONL（覆盖写，每次全量保存）。

        Args:
            todos: H-4 待办列表，非 None 时写入 todo_list 行
        """
        _validate_session_id(session_id)
        path = self.sessions_dir / f"{session_id}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            # 元数据首行
            meta = {
                "_type": "session_meta",
                "session_id": session_id,
                "emp_no": emp_no or "",
                "workspace": workspace or self.workspace or "",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            for msg in messages:
                if msg.get("_type") in ("session_meta", "todo_list"):
                    continue  # 跳过旧元数据和旧 todo_list，用新的替换
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            if metrics:
                f.write(json.dumps({"_type": "metrics", **metrics}, ensure_ascii=False) + "\n")
            # H-4: 写入待办列表
            if todos is not None:
                f.write(json.dumps({
                    "_type": "todo_list",
                    "todos": todos,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }, ensure_ascii=False) + "\n")
        # K-xxx：会话元数据投影到 SQLite 台账（agent 可脱离 workbench 独立跑，失败静默）
        try:
            import sys as _sys
            _bd = Path(__file__).resolve().parent.parent / "workbench" / "backend"
            if str(_bd) not in _sys.path:
                _sys.path.insert(0, str(_bd))
            from services import ledger_store
            count = len([m for m in messages if m.get("_type") not in ("session_meta", "todo_list")])
            tools = len([m for m in messages if m.get("tool_calls")])
            ledger_store.upsert_session(
                session_id, emp_no, workspace or self.workspace or "", count, tools)
        except Exception:
            pass  # 台账投影失败不影响会话落盘

    def append(self, session_id: str, message: dict):
        """追加单条消息到 JSONL。"""
        _validate_session_id(session_id)
        path = self.sessions_dir / f"{session_id}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def save_todos(self, session_id: str, todos: list[dict]):
        """H-4: 追加待办列表到 JSONL（即时持久化，save 会覆盖但也会重写）。"""
        _validate_session_id(session_id)
        path = self.sessions_dir / f"{session_id}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "_type": "todo_list",
                "todos": todos,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }, ensure_ascii=False) + "\n")

    def load_todos(self, session_id: str) -> Optional[list[dict]]:
        """H-4: 加载最新一份待办（取最后一行 todo_list）。"""
        _validate_session_id(session_id)
        path = self.sessions_dir / f"{session_id}.jsonl"
        if not path.is_file():
            return None
        last_todos = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if msg.get("_type") == "todo_list":
                        last_todos = msg.get("todos", [])
                except json.JSONDecodeError:
                    continue
        return last_todos

    def load(self, session_id: str) -> Optional[list[dict]]:
        """从 JSONL 加载会话消息列表。

        compaction_summary 消息保留为 system 消息（去掉 _type 字段），
        确保恢复会话时 LLM 能看到之前的压缩摘要。
        """
        _validate_session_id(session_id)
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
                msg_type = msg.get("_type")
                if msg_type in ("metrics", "session_meta", "todo_list"):
                    continue  # 跳过纯元数据行和待办行
                if msg_type == "compaction_summary":
                    # G3-1: 保留压缩摘要为 system 消息，去掉 _type 字段
                    msg = {k: v for k, v in msg.items() if k != "_type"}
                    msg["role"] = "system"
                messages.append(msg)
        return messages

    def list_sessions(self) -> list[dict]:
        """列出所有会话（含元数据 + 标题）。"""
        sessions = []
        for f in sorted(self.sessions_dir.glob("*.jsonl"), reverse=True):
            stat = f.stat()
            meta = self._read_meta(f)
            sessions.append({
                "id": f.stem,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "workspace": meta.get("workspace", ""),
                "emp_no": meta.get("emp_no", ""),
                "created_at": meta.get("created_at", ""),
                "title": meta.get("title", ""),
            })
        return sessions

    @staticmethod
    def _read_meta(path: Path) -> dict:
        """从 JSONL 首行读取元数据。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line:
                    data = json.loads(first_line)
                    if data.get("_type") == "session_meta":
                        return data
        except Exception:
            pass
        return {}

    def resume(self, session_id: str) -> Optional[list[dict]]:
        """恢复会话（等同于 load）。"""
        return self.load(session_id)

    def record_error(self, session_id: str, error: str, error_type: str = ""):
        """记录错误到会话 JSONL（用于导出和排查）。"""
        _validate_session_id(session_id)
        path = self.sessions_dir / f"{session_id}.jsonl"
        if not path.is_file():
            return
        entry = {
            "_type": "error",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "error": error[:1000],  # 限制长度
            "error_type": error_type,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def export_session(self, session_id: str) -> Optional[dict]:
        """导出完整会话（元数据 + 消息 + 指标 + 错误 + 调试信息），用于 JSON 导出。"""
        _validate_session_id(session_id)
        path = self.sessions_dir / f"{session_id}.jsonl"
        if not path.is_file():
            return None
        meta = {}
        messages = []
        metrics = None
        errors = []
        todos_data = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                msg_type = msg.get("_type")
                if msg_type == "session_meta":
                    meta = msg
                elif msg_type == "metrics":
                    metrics = msg
                elif msg_type == "error":
                    errors.append({k: v for k, v in msg.items() if k != "_type"})
                elif msg_type == "todo_list":
                    todos_data = msg.get("todos", [])
                elif msg_type == "compaction_summary":
                    msg = {k: v for k, v in msg.items() if k != "_type"}
                    msg["role"] = "system"
                    messages.append(msg)
                else:
                    messages.append(msg)

        # 读取 metrics JSONL 文件（逐轮计量数据）
        metrics_history = []
        metrics_path = self.sessions_dir / f"{session_id}_metrics.jsonl"
        if metrics_path.is_file():
            try:
                with open(metrics_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            metrics_history.append(json.loads(line))
            except Exception:
                pass

        # 统计摘要
        tool_calls = sum(1 for m in messages if m.get("role") == "tool")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")

        return {
            "session_id": session_id,
            "meta": meta,
            "messages": messages,
            "metrics": metrics,
            "metrics_history": metrics_history,  # 逐轮计量数据
            "errors": errors,  # 错误记录
            "todos": todos_data,  # H-4: 待办列表
            "summary": {
                "total_messages": len(messages),
                "assistant_messages": assistant_msgs,
                "tool_calls": tool_calls,
                "error_count": len(errors),
                "has_metrics": metrics is not None,
                "metrics_turns": len(metrics_history),
                "has_todos": todos_data is not None,
            },
            "exported_at": datetime.now().isoformat(timespec="seconds"),
        }
