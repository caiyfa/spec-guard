#!/usr/bin/env python3
"""T-1044 U4 ratchet 闸——工作台 UI 散点防回潮检查（新代码必须干净，旧代码慢慢还）。

用法：
  python workbench/frontend/scripts/ui_ratchet_check.py --all
      全量扫描（报告模式，输出各项计数与基线对照）
  python workbench/frontend/scripts/ui_ratchet_check.py --staged <file ...>
      pre-commit 模式：只查暂存的 ts/tsx 文件，命中即退出码 1（拒绝合入）

检查项（全部硬零，除 C 项为计数闸）：
  A 禁新增任意 text-[Npx] 散点字号（走 fs-micro/aux/body/lead/title 五档）
  B 禁新增原生 tailwind 状态色类名（text|bg|border|ring)-(red|green|yellow|amber|
    blue|purple|cyan|emerald|orange|pink)-N——一律六状态变量（pass/fail/skip/blocked/warn/info）
  C 手写弹层 fixed inset-0 计数不得超过存量基线（18 文件，登记 T-1045 迁移还清）；
    新文件一律禁止（弹层唯一实现 = components/Modal.tsx）
  D 内联 hex 颜色白名单外为 0（白名单：theme.ts 令牌表 / FocusGraph+NetworkGraph
    类别色板（T-1046 专项）/ ThemeSwitcher 默认值 / 测试文件）
"""
import pathlib
import re
import sys

FRONTEND = pathlib.Path(__file__).resolve().parent.parent
SRC = FRONTEND / "src"

RE_FONTSIZE = re.compile(r"text-\[\d+px\]")
RE_RAWCOLOR = re.compile(
    r"(?:text|bg|border|ring)-(?:red|green|yellow|amber|blue|purple|cyan|emerald|orange|pink)-\d")
RE_FIXED_OVERLAY = re.compile(r"fixed inset-0")
RE_HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")

# D 项白名单（路径相对 src/；前缀匹配）
HEX_WHITELIST = (
    "theme.ts",                       # JS_THEME_TOKENS 令牌表本体
    "components/ThemeSwitcher.tsx",   # railDot/pinnedBg 默认值（镜像主题变量）
    "components/FocusGraph.tsx",      # T-1046：类别色板按主题分档专项
    "components/NetworkGraph.tsx",    # T-1046：同上
)
# C 项存量基线（T-1045 迁移任务登记在册；新文件不得出现 fixed inset-0）
OVERLAY_BASELINE_FILES = {
    "components/FeishuWatchSettings.tsx", "components/ImageLightbox.tsx",
    "components/ComposeTopicModal.tsx", "components/ModelSetupModal.tsx",
    "components/TagRegistryModal.tsx", "components/TopicEditModal.tsx",
    "components/system-config/SystemsPanel.tsx", "components/system-config/WorkspacesPanel.tsx",
    "components/TopicWorkspace.tsx", "pages/DagEditor.tsx", "pages/GraphPanorama.tsx",
    "pages/NotifyConfigs.tsx", "pages/Schedules.tsx", "pages/agentChat/DraftArtifactsPanel.tsx",
    "pages/FeishuPool.tsx", "pages/agentChat/WritingPanel.tsx", "pages/agentChat/HistoryPanel.tsx",
    "components/Modal.tsx",
}


def is_test(path: str) -> bool:
    return path.endswith(".test.ts") or path.endswith(".test.tsx")


def scan_file(path: pathlib.Path, rel: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    for m in RE_FONTSIZE.finditer(text):
        problems.append(f"A 散点字号 {m.group()}")
    for m in RE_RAWCOLOR.finditer(text):
        problems.append(f"B 原生状态色 {m.group()}")
    if RE_FIXED_OVERLAY.search(text) and rel not in OVERLAY_BASELINE_FILES:
        problems.append("C 新增手写弹层 fixed inset-0（请用 components/Modal.tsx）")
    if not is_test(rel) and not any(rel.startswith(w) for w in HEX_WHITELIST):
        for m in RE_HEX.finditer(text):
            problems.append(f"D 内联 hex {m.group()}")
    return problems


def iter_source_files():
    for f in sorted(SRC.rglob("*")):
        if f.suffix in (".ts", ".tsx"):
            yield f, f.relative_to(SRC).as_posix()


def main() -> int:
    args = sys.argv[1:]
    if "--staged" in args:
        files = [a for a in args[args.index("--staged") + 1:] if a.endswith((".ts", ".tsx"))]
        bad: list[str] = []
        for raw in files:
            p = pathlib.Path(raw)
            if not p.is_absolute():
                p = (pathlib.Path.cwd() / p).resolve()
            if not p.exists() or FRONTEND not in p.parents:
                continue
            rel = p.relative_to(FRONTEND / "src").as_posix() if (FRONTEND / "src") in p.parents else p.name
            for prob in scan_file(p, rel):
                bad.append(f"{rel}: {prob}")
        if bad:
            print("U4 ratchet 闸拒绝合入（散点防回潮）：")
            for line in bad:
                print("  " + line)
            return 1
        return 0

    # --all：全量报告
    counts = {"A": 0, "B": 0, "C_new": 0, "D": 0}
    overlay_files = set()
    for f, rel in iter_source_files():
        for prob in scan_file(f, rel):
            key = prob.split()[0]
            if key == "C":
                counts["C_new"] += 1
            else:
                counts[key] = counts.get(key, 0) + 1
        if RE_FIXED_OVERLAY.search(f.read_text(encoding="utf-8")):
            overlay_files.add(rel)
    print(f"A 散点字号 text-[Npx]: {counts['A']}（硬零）")
    print(f"B 原生状态色类名: {counts['B']}（硬零）")
    print(f"C 手写弹层: {len(overlay_files)} 文件（基线 {len(OVERLAY_BASELINE_FILES)}；新增越基线 {counts['C_new']}）")
    print(f"D 白名单外内联 hex: {counts['D']}（硬零）")
    ok = counts["A"] == 0 and counts["B"] == 0 and counts["C_new"] == 0 and counts["D"] == 0
    print("U4 ratchet --all:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
