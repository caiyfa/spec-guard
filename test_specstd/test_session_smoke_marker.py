"""T-1041 会话列表 smoke 标记测试——smoke/ 子目录行打 smoke 标，前端默认隐藏。

背景（2026-08-29 验收注记）：smoke/ 是冒烟会话隔离区（验收/调试产物），但列表器
扫描全部子目录时把它们当普通会话混进树。约定：smoke/ 子目录的行打 smoke=True，
前端会话树默认过滤，批量操作内可开关查看（批量清理入口）。

全部离线：tmp_path 造目录 + 直调 _list_sessions_in_dir。
"""

import importlib
import json
import os
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import services.auth as auth_mod  # noqa: E402

importlib.reload(auth_mod)


def _write_session(emp_dir: Path, sub: str, sid: str, title: str = ""):
    """造一个最小会话文件：meta 行 + 一条 user 消息。"""
    d = emp_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    meta = {"_type": "session_meta", "session_id": sid, "emp_no": "90024166",
            "workspace": "人才发展", "purpose": "test_workbench", "purpose_locked": True}
    msg = {"role": "user", "content": title or "smoke 标记测试消息"}
    (d / f"{sid}.jsonl").write_text(
        json.dumps(meta, ensure_ascii=False) + "\n" + json.dumps(msg, ensure_ascii=False) + "\n",
        encoding="utf-8")


class TestListSmokeMarker:
    def test_smoke_dir_rows_marked(self, tmp_path):
        """smoke/ 子目录的会话行带 smoke=True；普通工作区与根目录行不带。"""
        from routers.agent import _list_sessions_in_dir
        _write_session(tmp_path, "人才发展", "20260829_100000_aaa11111")
        _write_session(tmp_path, "smoke", "20260829_110000_bbb22222")
        _write_session(tmp_path, ".", "20260829_120000_ccc33333")
        rows = {r["id"]: r for r in _list_sessions_in_dir(tmp_path)}
        assert rows["20260829_100000_aaa11111"].get("smoke") is None, "普通工作区行不打 smoke 标"
        assert rows["20260829_120000_ccc33333"].get("smoke") is None, "根目录行不打 smoke 标"
        assert rows["20260829_110000_bbb22222"].get("smoke") is True, "smoke/ 行必须打 smoke 标"

    def test_smoke_workspace_query_still_works(self, tmp_path):
        """显式 workspace=smoke 查询路径不回归（同步遍历分支不带标也如实返回）。"""
        from routers.agent import _list_sessions_in_dir
        _write_session(tmp_path, "smoke", "20260829_110000_bbb22222")
        rows = _list_sessions_in_dir(tmp_path, workspace="smoke")
        assert [r["id"] for r in rows] == ["20260829_110000_bbb22222"]
