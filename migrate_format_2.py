"""格式 2.0 一次性迁移脚本（文本外科手术，零噪音保真）。

为什么不用 ruamel 全量 round-trip：它会折叠多行纯量标量（db_query.sql、doc.given），
未触及区域也被重排，diff 噪音大且丢失人工排版。本脚本只做行级外科手术：
1. 领域步骤 → tool 信封（flow/teardown 内，flow/block 两种风格都处理）
2. 插入 version: "0.1"（title 行之后；加引号防止 YAML 解析为 float）
3. depends_on 补版本期望：标量 `- X` → `- {id: X, version: ^0}`；
   dict 流式 `- {id: X, mode: exclusive}` → 追加 `, version: ^0`（行内注释保留）
4. 重建 contracts_baseline.json（T6 校验基线）

用法：
    python migrate_format_2.py --dry-run    # 预览 diff，不写文件
    python migrate_format_2.py              # 执行迁移 + 重建契约基线
"""

import argparse
import difflib
import os
import re

SG_ROOT = os.path.dirname(os.path.abspath(__file__))

SCENARIOS_ROOT = os.path.join(SG_ROOT, "scenarios")

DOMAIN_STEPS = ("select_emp", "fetch_permission", "oss_upload", "oss_download", "random", "set_var")
_STEP_NAMES = "|".join(DOMAIN_STEPS)

# 段落识别（flow/teardown/depends_on 顶层 key）
_TOP_KEY = re.compile(r"^([a-z_]+):")
# flow 风格单行为步骤：`- select_emp: {...}`（可带行内注释）
_FLOW_STEP = re.compile(rf"^(\s*)- ({_STEP_NAMES}):\s*(\{{.*\}})(\s*(?:#.*)?)$")
# block 风格步骤头：`- select_emp:`（冒号后可带行内注释）
_BLOCK_STEP = re.compile(rf"^(\s*)- ({_STEP_NAMES}):(\s*(?:#.*)?)$")
# depends_on 标量项：`- PP-RC-001`（可带行内注释）
_DEP_SCALAR = re.compile(r"^(\s*)- ([A-Za-z][A-Za-z0-9-]*)(\s*(?:#.*)?)$")
# depends_on dict 流式项：`- {id: X, mode: exclusive}`（可带行内注释）
_DEP_DICT = re.compile(r"^(\s*)- \{id:\s*([^,}]+)([^}]*)\}(\s*(?:#.*)?)$")


def _split_top_level_commas(s):
    """按顶层逗号切分 flow map 内容（尊重嵌套 {} 与引号）"""
    parts, depth, quote, cur = [], 0, None, []
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch == "{":
            depth += 1
            cur.append(ch)
        elif ch == "}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return [p for p in parts if p]


def _envelope_flow_style(line):
    """flow 风格单行为步骤 → tool 信封单行"""
    m = _FLOW_STEP.match(line)
    if not m:
        return None
    indent, key, flow_map, tail = m.groups()
    parts = _split_top_level_commas(flow_map[1:-1])
    save_part, with_parts = None, []
    for p in parts:
        if re.match(r"^save\s*:", p):
            save_part = p
        else:
            with_parts.append(p)
    segs = [f"use: {key}"]
    if with_parts:
        segs.append("with: {" + ", ".join(with_parts) + "}")
    if save_part:
        segs.append(save_part)
    return f"{indent}- tool: {{{', '.join(segs)}}}{tail}"


def _migrate_block_step(lines, i):
    """block 风格步骤 → tool 信封。返回 (新行列表, 消耗行数)。

    缩进规则：use/with/save 对齐原步骤体实际缩进；with 内容在原基础上再进两格。
    """
    m = _BLOCK_STEP.match(lines[i])
    indent, key, tail = m.groups()
    # 收集步骤体行（缩进深于步骤行的后续行；空行随行）
    j = i + 1
    body_lines = []
    while j < len(lines):
        ln = lines[j]
        if ln.strip():
            cur_indent = len(ln) - len(ln.lstrip())
            if cur_indent <= len(indent):
                break
        body_lines.append(ln)
        j += 1
    # 步骤体实际缩进 = 第一个非空 body 行的缩进（兜底 dash+2）
    real_body_indent = None
    for bl in body_lines:
        if bl.strip():
            real_body_indent = len(bl) - len(bl.lstrip())
            break
    pad = " " * (real_body_indent if real_body_indent is not None else len(indent) + 2)

    save_lines, with_lines = [], []
    for bl in body_lines:
        if re.match(r"^\s*save\s*:", bl):
            save_lines.append(pad + bl.lstrip())   # save 归一到步骤体缩进（信封级）
        elif bl.strip():
            with_lines.append("  " + bl)            # 原缩进再进两格，挂到 with: 下
        else:
            with_lines.append(bl)
    new_lines = [f"{indent}- tool:{tail}",
                 f"{pad}use: {key}"]
    if with_lines:
        new_lines.append(f"{pad}with:")
        new_lines.extend(with_lines)
    new_lines.extend(save_lines)
    return new_lines, j - i


def _migrate_depends_line(line):
    """depends_on 行 → 补版本期望（已声明 version 的跳过）"""
    if "version:" in line:
        return line, False
    m = _DEP_SCALAR.match(line)
    if m and not m.group(2).startswith(("_", )):
        indent, dep_id, tail = m.groups()
        return f"{indent}- {{id: {dep_id}, version: ^0}}{tail}", True
    m = _DEP_DICT.match(line)
    if m:
        indent, dep_id, rest, tail = m.groups()
        return f"{indent}- {{id: {dep_id.strip()}{rest}, version: ^0}}{tail}", True
    return line, False


def migrate_text(original, counters):
    """全文行级迁移。返回迁移后文本。"""
    lines = original.splitlines()
    out = []
    section = None          # 当前顶层段落
    version_done = False
    i = 0
    while i < len(lines):
        line = lines[i]
        top = _TOP_KEY.match(line)
        if top and not line.startswith((" ", "\t")):
            section = top.group(1)

        # 1. version 字段插入（title 行之后，文件尚无 version 时）
        if not version_done and top and top.group(1) == "title" and "version" not in "".join(lines[:40]):
            out.append(line)
            out.append('version: "0.1"')
            counters["version"] += 1
            version_done = True
            i += 1
            continue

        # 2. depends_on 段落行
        if section == "depends_on" and line.lstrip().startswith("- "):
            new_line, changed = _migrate_depends_line(line)
            if changed:
                counters["deps"] += 1
            out.append(new_line)
            i += 1
            continue

        # 3. flow/teardown 段落步骤
        if section in ("flow", "teardown"):
            if _FLOW_STEP.match(line):
                out.append(_envelope_flow_style(line))
                counters["steps"] += 1
                i += 1
                continue
            if _BLOCK_STEP.match(line):
                new_lines, consumed = _migrate_block_step(lines, i)
                out.extend(new_lines)
                counters["steps"] += 1
                i += consumed
                continue

        out.append(line)
        i += 1

    result = "\n".join(out)
    if original.endswith("\n"):
        result += "\n"
    return result


def migrate_file(path, dry_run):
    with open(path, "r", encoding="utf-8") as f:
        original = f.read()
    counters = {"steps": 0, "deps": 0, "version": 0}
    migrated = migrate_text(original, counters)
    if migrated == original or not any(counters.values()):
        return None
    if dry_run:
        diff = difflib.unified_diff(
            original.splitlines(), migrated.splitlines(),
            fromfile=f"a/{os.path.basename(path)}", tofile=f"b/{os.path.basename(path)}",
            lineterm="",
        )
        return counters, "\n".join(diff)
    with open(path, "w", encoding="utf-8") as f:
        f.write(migrated)
    return counters, None


def rebuild_baseline():
    """迁移后重建契约基线（T6 比对基准）"""
    from engine.scenario_loader import load_scenarios
    from engine.versioning import build_baseline, save_baseline
    scenarios = load_scenarios(SCENARIOS_ROOT)
    baseline = build_baseline(scenarios)
    path = save_baseline(SG_ROOT, baseline)
    return path, len(baseline)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="仅预览 diff，不写文件")
    args = ap.parse_args()

    total = {"steps": 0, "deps": 0, "version": 0}
    files_changed = 0
    for dirpath, _dirs, filenames in os.walk(SCENARIOS_ROOT):
        for fn in sorted(filenames):
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            result = migrate_file(path, args.dry_run)
            if result is None:
                continue
            counters, diff = result
            files_changed += 1
            for k in total:
                total[k] += counters[k]
            rel = os.path.relpath(path, SCENARIOS_ROOT)
            print(f"{'[DRY] ' if args.dry_run else ''}{rel}: "
                  f"steps={counters['steps']} deps={counters['deps']} version={counters['version']}")
            if diff:
                print(diff)
                print()

    print(f"\n迁移{'预览' if args.dry_run else '完成'}: {files_changed} 个文件, "
          f"tool 信封化步骤 {total['steps']} 处, depends_on 版本化 {total['deps']} 处, "
          f"version 字段 {total['version']} 处")

    if not args.dry_run:
        path, count = rebuild_baseline()
        print(f"契约基线已重建: {path}（{count} 个场景）")


if __name__ == "__main__":
    main()
