"""test_workbench 装配：把 workbench/backend 加入 sys.path（与 test_specstd 同构）。"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "workbench" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
