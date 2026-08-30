#!/usr/bin/env python3
"""T-1044 U0-2 字号阶梯 codemod——单映射替换（一档一提交）。

用法: python scripts/u0_fontsize_codemod.py "text-[9px]" "text-fs-micro" [--apply]
默认 dry-run（只报告）；--apply 实写。纯文本 token 替换（tailwind 类名原子性，
variant 前缀 hover:/sm: 与 ! 重要修饰天然兼容），范围 src/**/*.{ts,tsx}。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "src"


def main() -> int:
    old, new = sys.argv[1], sys.argv[2]
    apply = "--apply" in sys.argv
    total, files = 0, 0
    for f in sorted(ROOT.rglob("*")):
        if f.suffix not in (".ts", ".tsx"):
            continue
        text = f.read_text(encoding="utf-8")
        n = text.count(old)
        if not n:
            continue
        files += 1
        total += n
        if apply:
            f.write_text(text.replace(old, new), encoding="utf-8")
        print(f"  {f.relative_to(ROOT)}: {n}")
    print(f"{'APPLIED' if apply else 'DRY-RUN'}: {old} -> {new} | {files} files, {total} replacements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
