#!/usr/bin/env python3
"""T-1044 U0-3 逃逸色清剿 codemod——按族映射到主题状态变量（B·Paper 透明度档：淡填 12% / 描边 35%）。

用法: python scripts/u0_color_codemod.py <family> [--apply]
family: red | green | warn | blue | purple | emerald | overlay | all
规则要点：
  - 长 token 先替换（bg-red-900/40 先于 bg-red-900），防 opacity 后缀断裂
  - text-*/80 等修饰保留（text-fail/80 合法）；bg-*-900/NN 一律归 bg-var/12（B 淡填档）
  - 实心 bg-*-500/600 → bg-var（主题自适应实色）；border-* → border-var/35（B 描边档）
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "src"

# (old, new)，全局按序执行（长 token 在前）
FAMILIES = {
    "red": [
        ("text-red-400/80", "text-fail/80"), ("text-red-400/90", "text-fail/90"),
        ("text-red-400", "text-fail"), ("text-red-300", "text-fail"), ("text-red-500", "text-fail"),
        ("bg-red-900/10", "bg-fail/12"), ("bg-red-900/20", "bg-fail/12"), ("bg-red-900/30", "bg-fail/12"),
        ("bg-red-900/40", "bg-fail/12"), ("bg-red-900/50", "bg-fail/12"), ("bg-red-900/60", "bg-fail/12"),
        ("bg-red-900", "bg-fail/12"),
        ("bg-red-500/10", "bg-fail/12"), ("bg-red-500/60", "bg-fail"), ("bg-red-500", "bg-fail"),
        ("bg-red-600", "bg-fail"),
        ("border-red-700/30", "border-fail/35"), ("border-red-700/50", "border-fail/35"),
        ("border-red-700", "border-fail/35"),
        ("border-red-500/30", "border-fail/35"), ("border-red-500/50", "border-fail/35"),
        ("border-red-500/60", "border-fail/35"), ("border-red-500", "border-fail/35"),
        ("border-red-900", "border-fail/35"),
        ("ring-red-500/50", "ring-fail/50"), ("ring-red-500", "ring-fail"),
    ],
    "green": [
        ("text-green-400/80", "text-pass/80"),
        ("text-green-400", "text-pass"), ("text-green-300", "text-pass"), ("text-green-500", "text-pass"),
        ("bg-green-900/20", "bg-pass/12"), ("bg-green-900/30", "bg-pass/12"), ("bg-green-900/40", "bg-pass/12"),
        ("bg-green-900/50", "bg-pass/12"), ("bg-green-900/60", "bg-pass/12"), ("bg-green-900", "bg-pass/12"),
        ("bg-green-500/10", "bg-pass/12"), ("bg-green-500/20", "bg-pass/12"), ("bg-green-500", "bg-pass"),
        ("bg-green-600", "bg-pass"),
        ("border-green-700/30", "border-pass/35"), ("border-green-700/50", "border-pass/35"),
        ("border-green-700", "border-pass/35"),
        ("border-green-500/40", "border-pass/35"), ("border-green-500/60", "border-pass/35"),
        ("border-green-500", "border-pass/35"),
        ("ring-green-500/50", "ring-pass/50"), ("ring-green-500", "ring-pass"),
    ],
    "warn": [  # yellow + amber + orange 全归 warn（语义=警示/进行中）
        ("text-yellow-400/80", "text-warn/80"), ("text-yellow-500/80", "text-warn/80"),
        ("text-yellow-500/50", "text-warn/50"),
        ("text-yellow-400", "text-warn"), ("text-yellow-300", "text-warn"),
        ("text-yellow-500", "text-warn"), ("text-yellow-100", "text-warn"),
        ("bg-yellow-900/20", "bg-warn/12"), ("bg-yellow-900/30", "bg-warn/12"),
        ("bg-yellow-900/40", "bg-warn/12"), ("bg-yellow-900/50", "bg-warn/12"),
        ("bg-yellow-900", "bg-warn/12"),
        ("bg-yellow-500/10", "bg-warn/12"), ("bg-yellow-500", "bg-warn"),
        ("border-yellow-700/30", "border-warn/35"), ("border-yellow-700/50", "border-warn/35"),
        ("border-yellow-700", "border-warn/35"), ("border-yellow-500/50", "border-warn/35"),
        ("text-amber-300/80", "text-warn/80"), ("text-amber-400/90", "text-warn/90"),
        ("text-amber-500/80", "text-warn/80"),
        ("text-amber-400", "text-warn"), ("text-amber-300", "text-warn"), ("text-amber-500", "text-warn"),
        ("bg-amber-900/10", "bg-warn/12"), ("bg-amber-900/30", "bg-warn/12"), ("bg-amber-900/50", "bg-warn/12"),
        ("bg-amber-900", "bg-warn/12"),
        ("bg-amber-500/10", "bg-warn/12"), ("bg-amber-500/15", "bg-warn/12"), ("bg-amber-500", "bg-warn"),
        ("border-amber-500/30", "border-warn/35"), ("border-amber-500/40", "border-warn/35"),
        ("border-amber-500/60", "border-warn/35"), ("border-amber-500", "border-warn/35"),
        ("text-orange-400", "text-warn"), ("text-orange-300", "text-warn"),
        ("bg-orange-900/30", "bg-warn/12"), ("bg-orange-900/40", "bg-warn/12"), ("bg-orange-900", "bg-warn/12"),
        ("bg-orange-500", "bg-warn"), ("border-orange-500/40", "border-warn/35"),
    ],
    "blue": [  # blue + cyan 全归 info
        ("text-blue-200/80", "text-info/80"),
        ("text-blue-400", "text-info"), ("text-blue-300", "text-info"), ("text-blue-200", "text-info"),
        ("bg-blue-900/20", "bg-info/12"), ("bg-blue-900/30", "bg-info/12"), ("bg-blue-900/40", "bg-info/12"),
        ("bg-blue-900/50", "bg-info/12"), ("bg-blue-900", "bg-info/12"),
        ("bg-blue-500/15", "bg-info/12"), ("bg-blue-500/10", "bg-info/12"),
        ("bg-blue-600", "bg-info"), ("bg-blue-500", "bg-info"), ("bg-blue-700", "bg-info"),
        ("border-blue-700/50", "border-info/35"), ("border-blue-700", "border-info/35"),
        ("border-blue-500/60", "border-info/35"), ("border-blue-500/40", "border-info/35"),
        ("border-blue-500", "border-info/35"),
        ("text-cyan-400", "text-info"), ("text-cyan-300", "text-info"), ("text-cyan-200", "text-info"),
        ("bg-cyan-900/30", "bg-info/12"), ("bg-cyan-900/40", "bg-info/12"), ("bg-cyan-900/50", "bg-info/12"),
        ("bg-cyan-900/70", "bg-info/12"), ("bg-cyan-900", "bg-info/12"),
        ("bg-cyan-400", "bg-info"),
        ("border-cyan-500/30", "border-info/35"), ("border-cyan-500/60", "border-info/35"),
        ("border-cyan-500", "border-info/35"),
    ],
    "purple": [  # purple 全归 blocked
        ("text-purple-300", "text-blocked"), ("text-purple-200", "text-blocked"),
        ("text-purple-400", "text-blocked"),
        ("bg-purple-900/10", "bg-blocked/12"), ("bg-purple-900/30", "bg-blocked/12"),
        ("bg-purple-900/40", "bg-blocked/12"), ("bg-purple-900/50", "bg-blocked/12"),
        ("bg-purple-900/70", "bg-blocked/12"), ("bg-purple-900", "bg-blocked/12"),
        ("bg-purple-500", "bg-blocked"),
        ("border-purple-500/30", "border-blocked/35"), ("border-purple-500/40", "border-blocked/35"),
        ("border-purple-500/60", "border-blocked/35"), ("border-purple-500", "border-blocked/35"),
    ],
    "emerald": [  # emerald 归 pass
        ("text-emerald-400", "text-pass"), ("text-emerald-300", "text-pass"),
        ("bg-emerald-500/10", "bg-pass/12"), ("bg-emerald-500", "bg-pass"),
        ("border-emerald-500/30", "border-pass/35"), ("border-emerald-500", "border-pass/35"),
    ],
    "overlay": [  # bg-black/NN 固定黑叠层 → 主题 overlay 变量（需先在 tailwind.config 桥接 overlay 色）
        ("bg-black/20", "bg-overlay/20"), ("bg-black/30", "bg-overlay/30"),
        ("bg-black/40", "bg-overlay/40"), ("bg-black/50", "bg-overlay/50"),
        ("bg-black/60", "bg-overlay/60"), ("bg-black/70", "bg-overlay/70"),
    ],
}


def main() -> int:
    fam, apply = sys.argv[1], "--apply" in sys.argv
    rules = FAMILIES[fam] if fam != "all" else [r for v in FAMILIES.values() for r in v]
    total, files = 0, 0
    for f in sorted(ROOT.rglob("*")):
        if f.suffix not in (".ts", ".tsx"):
            continue
        text = f.read_text(encoding="utf-8")
        out, cnt = text, 0
        for old, new in rules:
            n = out.count(old)
            if n:
                out = out.replace(old, new)
                cnt += n
        if not cnt:
            continue
        files += 1
        total += cnt
        if apply:
            f.write_text(out, encoding="utf-8")
        print(f"  {f.relative_to(ROOT)}: {cnt}")
    print(f"{'APPLIED' if apply else 'DRY-RUN'} [{fam}] | {files} files, {total} replacements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
