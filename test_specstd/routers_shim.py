"""测试直调桥：从 agent.py 取 _parent_snapshot/_viewing_context_block（不装配整个 FastAPI app）。"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "workbench" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from routers.agent import _parent_snapshot, _viewing_context_block  # noqa: F401,E402
