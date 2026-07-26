"""depends_on 文本外科手术编辑器（保注释、零噪音）。

画布连线操作 → 场景 YAML depends_on 段的行级增删。
与 migrate_format_2.py 同策略：纯行级文本编辑，不做全量 YAML round-trip，
保留全部人工注释、排版与未触及区域字节。
"""

import re

# 依赖行中的 id 提取（标量 `- X` 或 dict 流式 `- {id: X, ...}`）
_DEP_LINE_ID = re.compile(r"^\s*-\s+(?:\{id:\s*)?([A-Za-z][A-Za-z0-9-]*)")
_TOP_KEY = re.compile(r"^([a-zA-Z_]+)")


class DepsEditError(Exception):
    pass


def expected_version_of(dep_actual_version: str) -> str:
    """由被依赖方当前版本推导期望声明：^{major}（快照期 ^0，release 后 ^1...）"""
    return "^" + str(dep_actual_version).split(".")[0]


def _find_dep_section(lines):
    """定位 depends_on 段。返回 (header_idx, item_end_idx)；无段落返回 (None, None)。

    item_end_idx：段内最后一个依赖行的下一行行号（插入点）。
    """
    header_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^depends_on\s*:", ln):
            header_idx = i
            break
    if header_idx is None:
        return None, None
    j = header_idx + 1
    last_item = header_idx
    while j < len(lines):
        ln = lines[j]
        if ln.strip() == "":
            j += 1
            continue
        if ln.lstrip().startswith("- ") or ln.lstrip().startswith("#"):
            if ln.lstrip().startswith("- "):
                last_item = j
            j += 1
            continue
        break   # 遇到下一个顶层 key 或非依赖内容
    return header_idx, last_item + 1


def _section_dep_ids(lines, header_idx, end_idx):
    """段内全部依赖 id 列表"""
    ids = []
    for ln in lines[header_idx:end_idx]:
        m = _DEP_LINE_ID.match(ln)
        if m:
            ids.append(m.group(1))
    return ids


def add_dep(path: str, dep_id: str, mode: str, dep_actual_version: str) -> None:
    """向场景 YAML 追加一条依赖（重复 → DepsEditError）。

    mode=shared 时省略 mode 键（保持简洁）；version 期望 = ^{dep 当前主版本}。
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    expect = expected_version_of(dep_actual_version)
    kv = f"id: {dep_id}"
    if mode == "exclusive":
        kv += ", mode: exclusive"
    new_line = f"  - {{{kv}, version: {expect}}}"

    header_idx, end_idx = _find_dep_section(lines)
    if header_idx is None:
        # 无 depends_on 段 → 在 flow: 前插入整段
        flow_idx = next((i for i, ln in enumerate(lines) if re.match(r"^flow\s*:", ln)), None)
        if flow_idx is None:
            raise DepsEditError("文件缺少 flow 段，无法定位插入点")
        lines[flow_idx:flow_idx] = ["depends_on:", new_line]
    elif lines[header_idx].strip() == "depends_on: []":
        lines[header_idx] = "depends_on:"
        lines.insert(header_idx + 1, new_line)
    else:
        if dep_id in _section_dep_ids(lines, header_idx, end_idx):
            raise DepsEditError(f"依赖已存在: {dep_id}")
        lines.insert(end_idx, new_line)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def remove_dep(path: str, dep_id: str) -> None:
    """从场景 YAML 移除一条依赖（不存在 → DepsEditError）。段空时改写为 depends_on: []"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    header_idx, end_idx = _find_dep_section(lines)
    if header_idx is None:
        raise DepsEditError("场景无 depends_on 段")

    target_idx = None
    for i in range(header_idx + 1, end_idx):
        m = _DEP_LINE_ID.match(lines[i])
        if m and m.group(1) == dep_id:
            target_idx = i
            break
    if target_idx is None:
        raise DepsEditError(f"依赖不存在: {dep_id}")

    del lines[target_idx]
    # 段内已无依赖行 → 折叠为 depends_on: []
    remaining = 0
    for ln in lines[header_idx + 1:]:
        if ln.strip() == "":
            continue
        if ln.lstrip().startswith("- "):
            remaining += 1
            continue
        break   # 下一个顶层 key
    if remaining == 0:
        lines[header_idx] = "depends_on: []"

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
