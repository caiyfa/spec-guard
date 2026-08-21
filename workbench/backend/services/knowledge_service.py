"""knowledge_service — 知识维护页服务（T-509：词条/环境叙事/经验队列）。

职责：
- 词条：读当前工作区 glossary.md；保存即 conformance 校验（词条引用 FR 断链标红）
- 环境叙事：读/写 systems/{system}/config/env.{env}.md；凭据红线校验
- 经验队列：读 {ws}/.specguard/experience/ 目录（T-510 落行后消费）

纪律：
- 知识按工作区/系统隔离——词条从当前激活工作区解析，叙事从当前系统适配包解析
- 写操作 RBAC（admin/tester）+ 审计留痕（user_store.audit）
- 校验逻辑确定性（specstd 解析 + anchors 比对），无 LLM 路由
"""

import re
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent

from specstd.glossary import parse_glossary, GLOSSARY_FILE, extract_fr_refs
from specstd.anchors import scan_anchors

# 凭据红线模式（环境叙事永不写凭据）
CREDENTIAL_PATTERNS = [
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:：=]\s*\S+"), "password"),
    (re.compile(r"(?i)(secret|client_secret|app_secret)\s*[:：=]\s*\S+"), "secret"),
    (re.compile(r"(?i)(token|access_token)\s*[:：=]\s*\S+"), "token"),
    (re.compile(r"(?i)(api[_-]?key|apikey)\s*[:：=]\s*\S+"), "api key"),
    (re.compile(r"(?i)(private[_-]?key|BEGIN [A-Z ]*PRIVATE KEY)"), "private key"),
]


def _active_workspace_root() -> Path:
    """解析当前激活工作区根（无激活抛 ValueError）。"""
    from specstd.workspace import get_workspace_root
    root = get_workspace_root()
    if root is None:
        raise ValueError("无激活工作区")
    return Path(root)


def _active_system() -> str:
    """当前激活工作区的系统名。"""
    from specstd.workspace import get_active_workspace
    ws = get_active_workspace()
    if not ws:
        raise ValueError("无激活工作区")
    return ws.system


# ══════════════════════════════════════════════════════════
# 词条
# ══════════════════════════════════════════════════════════

def load_glossary() -> dict:
    """读取当前工作区词典：词条列表 + 断链校验发现。

    返回 {path, text, entries, findings}
    findings: [{level, message, token}]——词条引用的 FR 在 anchors 中不存在 → ERROR。
    """
    root = _active_workspace_root()
    gpath = root / GLOSSARY_FILE
    if not gpath.is_file():
        return {"path": str(gpath), "text": "", "entries": [], "findings": []}

    text = gpath.read_text(encoding="utf-8")
    entries = parse_glossary(gpath)
    fr_map = extract_fr_refs(entries)
    anchors = scan_anchors(root)

    findings = []
    for e in entries:
        for fr in fr_map.get(e.token, []):
            if fr not in anchors:
                findings.append({
                    "level": "ERROR",
                    "token": e.token,
                    "message": f"词条「{e.title}」引用的 FR {fr} 在当前工作区 spec.md 中不存在（断链）",
                })
    return {"path": str(gpath), "text": text,
            "entries": [e.to_dict() for e in entries], "findings": findings}


def save_glossary(text: str, emp: str = "") -> dict:
    """保存词条全文 + 保存即校验（断链标红）+ 审计留痕。

    保存策略：全文替换（Monaco 编辑整体文件，非逐条 round-trip——保中文注释）。
    """
    root = _active_workspace_root()
    gpath = root / GLOSSARY_FILE
    gpath.parent.mkdir(parents=True, exist_ok=True)
    gpath.write_text(text, encoding="utf-8")

    # 保存即 conformance 校验（断链标红）
    result = load_glossary()
    n_err = sum(1 for f in result["findings"] if f["level"] == "ERROR")

    # 审计留痕（失败不阻断保存）
    try:
        from services import user_store
        user_store.audit(emp, "knowledge_write", str(gpath.relative_to(root)),
                         detail=f"glossary 保存 {len(result['entries'])} 词条，断链 {n_err}")
    except Exception:
        pass

    return result


# ══════════════════════════════════════════════════════════
# 环境叙事
# ══════════════════════════════════════════════════════════

def list_env_narratives() -> list[dict]:
    """列出当前系统的环境叙事文件（env.{env}.md）。"""
    system = _active_system()
    cfg_dir = SG_ROOT / "systems" / system / "config"
    out = []
    if cfg_dir.is_dir():
        for f in sorted(cfg_dir.glob("env.*.md")):
            out.append({
                "env": f.stem.split(".", 1)[1],
                "path": str(f.relative_to(SG_ROOT)),
                "text": f.read_text(encoding="utf-8"),
            })
    return out


def load_env_narrative(env: str) -> dict:
    """读取指定环境的叙事（含凭据红线预检）。"""
    if not env or not re.fullmatch(r"[A-Za-z0-9_-]+", env):
        raise ValueError(f"非法环境名: {env!r}")
    system = _active_system()
    env_md = SG_ROOT / "systems" / system / "config" / f"env.{env}.md"
    if not env_md.is_file():
        raise FileNotFoundError(f"环境叙事不存在: {env_md}")
    text = env_md.read_text(encoding="utf-8")
    return {"env": env, "path": str(env_md.relative_to(SG_ROOT)),
            "text": text, "findings": _credential_check(text)}


def save_env_narrative(env: str, text: str, emp: str = "") -> dict:
    """保存环境叙事 + 凭据红线校验（含凭据 → 拒绝）+ 审计留痕。"""
    if not env or not re.fullmatch(r"[A-Za-z0-9_-]+", env):
        raise ValueError(f"非法环境名: {env!r}")
    # 凭据红线：永不写凭据（含凭据直接拒绝，不落盘）
    findings = _credential_check(text)
    hard_errors = [f for f in findings if f["level"] == "ERROR"]
    if hard_errors:
        return {"saved": False, "findings": findings,
                "message": "凭据红线：环境叙事禁止写入凭据（password/secret/token），已拒绝保存"}

    system = _active_system()
    cfg_dir = SG_ROOT / "systems" / system / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_md = cfg_dir / f"env.{env}.md"
    env_md.write_text(text, encoding="utf-8")

    # 审计留痕
    try:
        from services import user_store
        user_store.audit(emp, "knowledge_write", str(env_md.relative_to(SG_ROOT)),
                         detail=f"env.{env}.md 叙事保存（凭据红线通过）")
    except Exception:
        pass
    return {"saved": True, "findings": findings, "message": "环境叙事已保存"}


def _credential_check(text: str) -> list[dict]:
    """凭据红线校验：命中凭据模式 → ERROR/WARN。

    含实际值（=xxx 非空）→ ERROR；仅字段名/占位符 → WARN（提示不写真实值）。
    """
    findings = []
    for pattern, kind in CREDENTIAL_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(0).split(":", 1)[-1].split("=", 1)[-1].strip()
            if value and value not in ("xxx", "***", "待补充", "TODO"):
                findings.append({
                    "level": "ERROR",
                    "kind": kind,
                    "message": f"疑似凭据写入：{m.group(0)[:60]}（红线：叙事层永不写凭据）",
                })
            else:
                findings.append({
                    "level": "WARN",
                    "kind": kind,
                    "message": f"提及凭据字段 {kind}（请确认仅描述不写值）",
                })
    return findings[:10]


# ══════════════════════════════════════════════════════════
# 经验队列（T-510 落行后消费；此处只读列表）
# ══════════════════════════════════════════════════════════

def list_experience_queue() -> list[dict]:
    """经验库列表（{ws}/.specguard/experience/*.md，T-510 增强字段）。"""
    root = _active_workspace_root()
    exp_dir = Path(root) / ".specguard" / "experience"
    out = []
    if exp_dir.is_dir():
        # 优先走 experience_store 登记（含 hit_count/rating/corrected）
        try:
            from services import experience_store
            return experience_store.list_experiences(root)
        except Exception:
            pass
        for f in sorted(exp_dir.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            title = f.stem
            m = re.search(r"(EX-[A-Za-z0-9]+)", f.stem)
            if m:
                title = m.group(1)
            out.append({
                "token": title,
                "path": str(f.relative_to(root)),
                "text": text[:2000],
                "source": "experience",
            })
    return out
