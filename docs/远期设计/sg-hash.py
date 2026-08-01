#!/usr/bin/env python3
"""sg-hash.py — SpecGuard 总控文档登记用文件指纹工具
指纹算法：SHA-256 取前 12 位（与平台 specstd/signature.py 契约指纹口径一致）。

用法：
  python3 sg-hash.py <file>                 # 计算文件指纹（登记「修改前hash」用）
  python3 sg-hash.py --check <file> <hash>  # 核对文件是否被改动（开工前校验用）
  python3 sg-hash.py --check-all <登记行>   # 预留：批量核对（格式 路径|hash，每行一条）
退出码：0 = 一致/计算成功；1 = 不一致；2 = 用法错误/文件不存在
"""
import hashlib
import sys
from pathlib import Path

ALGO = "sha256"
DIGEST_LEN = 12


def file_hash(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        print(f"ERROR: 文件不存在 {path}", file=sys.stderr)
        sys.exit(2)
    h = hashlib.new(ALGO)
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:DIGEST_LEN]


def main(argv):
    if len(argv) == 2 and not argv[1].startswith("-"):
        print(file_hash(argv[1]))
        return 0
    if len(argv) == 3 and argv[1] == "--check-all":
        bad = 0
        for line in Path(argv[2]).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            path, expect = [s.strip() for s in line.split("|")][:2]
            actual = file_hash(path)
            mark = "OK  " if actual == expect else "DIFF"
            if actual != expect:
                bad += 1
            print(f"{mark} {path}  登记={expect} 实际={actual}")
        return 1 if bad else 0
    if len(argv) == 4 and argv[1] == "--check":
        actual = file_hash(argv[2])
        if actual == argv[3]:
            print(f"OK  {argv[2]}  hash={actual} 未变更")
            return 0
        print(f"DIFF {argv[2]}  登记={argv[3]} 实际={actual} —— 文件已被修改，停手核对总控文档登记表！", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
