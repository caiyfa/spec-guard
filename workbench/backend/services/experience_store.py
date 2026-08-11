"""experience_store — 经验飞轮存储（T-510，deepferry memory.py 移植）。

双轨制：
- 自动层：run 终局落行（FAIL/BLOCKED/ERROR 场景 → 五段式经验草稿 .md +
  _meta.json 结构化登记）；用户纠正关键词检测 → corrected 状态；recency×hit_count
  检索注入（≤2KB 封顶）；👍/👎 反馈。
- 人工层：反复命中后经知识页提炼为经验包（docs/经验包五段式既有流程）。

存储按工作区隔离：{ws}/.specguard/experience/{token}.md + _meta.json。
设计对齐 failure_index：只追加不修改（_meta.json 为登记层）、幂等、读路径纯读。
"""

import json
import re
import time
from pathlib import Path

META_FILE = "_meta.json"
# 检索注入预算硬顶（设计 §2.3：≤2KB 封顶）
SEARCH_BUDGET = 2000

# 用户纠正关键词（命中 → 该轮经验标 corrected）
CORRECTION_KEYWORDS = (
    "不对", "错了", "不是这样", "应该是", "其实是", "纠正", "重新看",
    "搞错了", "理解错", "修正",
)

# run 终局落行范围（诚实结果：失败才落，PASS 不落）
EXP_VERDICTS = ("FAIL", "ERROR", "BLOCKED")


def _meta_path(exp_dir: Path) -> Path:
    return exp_dir / META_FILE


def _load_meta(exp_dir: Path) -> dict:
    p = _meta_path(exp_dir)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_meta(exp_dir: Path, meta: dict):
    exp_dir.mkdir(parents=True, exist_ok=True)
    tmp = _meta_path(exp_dir).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_meta_path(exp_dir))


def _token_for(run_id: str, scenario_id: str, n: int) -> str:
    """经验 token：{scenario}-{run_id} 或加序号（同 run 多失败场景）。"""
    return f"{scenario_id}-{run_id}-{n}"


# ══════════════════════════════════════════════════════════
# run 终局落行
# ══════════════════════════════════════════════════════════

def append_experience(reports_root: Path, run_id: str, ws_root: Path) -> int:
    """run 终局落行：失败场景 → 经验草稿（五段式 .md）+ _meta.json 登记。

    返回落行条数；run.json 不存在返回 0；幂等（同一 run_id 不重复落）。
    """
    reports_root = Path(reports_root)
    run_json = reports_root / run_id / "run.json"
    if not run_json.is_file():
        return 0
    try:
        run_data = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:
        return 0

    exp_dir = Path(ws_root) / ".specguard" / "experience"
    meta = _load_meta(exp_dir)
    # 幂等：run_id 已在登记 → 跳过
    if any(m.get("run_id") == run_id for m in meta.values()):
        return 0

    added = 0
    for case in run_data.get("cases", []):
        verdict = case.get("verdict", "")
        if verdict not in EXP_VERDICTS:
            continue
        sid = case.get("id", "")
        if not sid:
            continue
        # 失败详情（failure 在 cases/{id}.json）
        detail = {}
        case_file = case.get("file") or ""
        case_path = None
        if case_file:
            case_path = reports_root / run_id / case_file
            if not case_path.is_file():
                case_path = reports_root / run_id / "cases" / Path(case_file).name
        if case_path and case_path.is_file():
            try:
                detail = json.loads(case_path.read_text(encoding="utf-8"))
            except Exception:
                detail = {}
        failure = detail.get("failure") or {}
        message = failure.get("message", "") or ""
        category = failure.get("category", "") or ""

        added += 1
        token = _token_for(run_id, sid, added)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        md = _draft_md(token, run_id, sid, verdict, message, category, now)
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / f"{token}.md").write_text(md, encoding="utf-8")
        meta[token] = {
            "token": token,
            "run_id": run_id,
            "scenario_id": sid,
            "verdict": verdict,
            "category": category,
            "message": message[:200],
            "hit_count": 0,
            "rating": "",
            "corrected": False,
            "created_at": now,
            "updated_at": now,
        }

    if added:
        _save_meta(exp_dir, meta)
    return added


def _draft_md(token: str, run_id: str, sid: str, verdict: str,
              message: str, category: str, now: str) -> str:
    """五段式经验草稿（docs/经验包模板同构，供知识页提炼）。"""
    return (
        f"# 经验草稿：{token} · {sid}（{verdict}）\n\n"
        f"> 任务号：{run_id} ｜ 场景：{sid} ｜ verdict：{verdict} ｜ 落行：{now}\n\n"
        f"## 现象\n\n{message or '（待补充失败信息）'}\n\n"
        f"## 证据链\n\n（待补充——cases/{sid}.json 的 body_excerpt / output.log 调用链）\n\n"
        f"## 根因\n\n（待提炼——环境 / 场景 / 引擎 / 配置 四选一，须证据链支持）\n\n"
        f"## 修复\n\n（待提炼）\n\n"
        f"## 预防\n\n（待提炼）\n\n"
        f"---\n\n> 自动落行草稿（category={category or '未知'}）。反复命中后经知识页提炼为经验包。\n"
    )


# ══════════════════════════════════════════════════════════
# 用户纠正关键词检测
# ══════════════════════════════════════════════════════════

def detect_correction(text: str) -> bool:
    """用户纠正关键词检测（命中 → corrected 信号）。"""
    if not text:
        return False
    return any(kw in text for kw in CORRECTION_KEYWORDS)


def mark_corrected(ws_root: Path, token: str) -> bool:
    """标记经验条目为 corrected（用户纠正留痕）。"""
    exp_dir = Path(ws_root) / ".specguard" / "experience"
    meta = _load_meta(exp_dir)
    if token not in meta:
        return False
    meta[token]["corrected"] = True
    meta[token]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_meta(exp_dir, meta)
    return True


# ══════════════════════════════════════════════════════════
# 检索（recency×hit_count，≤2KB 封顶）
# ══════════════════════════════════════════════════════════

def search_experiences(ws_root: Path, query: str,
                       limit: int = SEARCH_BUDGET) -> list[dict]:
    """检索经验：关键词命中 → recency×hit_count 排序 → 摘要注入（≤limit 封顶）。

    命中即递增 hit_count（检索注入的信号源）；返回按 score 降序的条目列表，
    text 为五段式正文截断。物理隔离：仅扫当前工作区经验库。
    """
    exp_dir = Path(ws_root) / ".specguard" / "experience"
    if not exp_dir.is_dir():
        return []
    meta = _load_meta(exp_dir)
    query = (query or "").strip().lower()
    if not query:
        return []

    # token 化匹配：按非字母数字切分（中文/英文/ID 均覆盖），任一 token 命中即算
    # （整句子串匹配会漏——纠正句整句不可能出现在经验文本中）
    tokens = [t for t in re.split(r"[^\w\u4e00-\u9fff]+", query) if len(t) >= 2]
    if not tokens:
        return []

    scored = []
    for md in sorted(exp_dir.glob("*.md")):
        if md.name == META_FILE:
            continue
        text = md.read_text(encoding="utf-8")
        low = text.lower()
        if not any(t in low for t in tokens):
            continue
        info = meta.get(md.stem, {})
        hit_count = int(info.get("hit_count", 0))
        created = info.get("created_at", "")
        # recency：新近落行加权（日序号，粗略 recency 信号）
        day = 0
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", created)
        if m:
            day = int(m.group(3))  # 月内日序号（简单近似）
        score = hit_count * 10 + day
        scored.append({
            "token": md.stem,
            "score": score,
            "hit_count": hit_count + 1,  # 本次命中后（已递增）
            "rating": info.get("rating", ""),
            "corrected": info.get("corrected", False),
            "created_at": created,
            "text": text,
        })
        # 检索命中 → 递增 hit_count（落盘）
        info["hit_count"] = hit_count + 1
        info["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if scored:
        _save_meta(exp_dir, meta)

    scored.sort(key=lambda r: r["score"], reverse=True)
    # ≤limit 封顶：从最高分开始累加文本长度
    out, total = [], 0
    for r in scored:
        if total + len(r["text"]) > limit:
            continue
        out.append(r)
        total += len(r["text"])
    return out


# ══════════════════════════════════════════════════════════
# 👍/👎 反馈
# ══════════════════════════════════════════════════════════

def rate_experience(ws_root: Path, token: str, rating: str) -> bool:
    """👍/👎 反馈（rating ∈ up/down）。"""
    if rating not in ("up", "down"):
        return False
    exp_dir = Path(ws_root) / ".specguard" / "experience"
    meta = _load_meta(exp_dir)
    if token not in meta:
        return False
    meta[token]["rating"] = rating
    meta[token]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_meta(exp_dir, meta)
    return True


def list_experiences(ws_root: Path) -> list[dict]:
    """经验队列列表（知识页「经验审核」区消费）。"""
    exp_dir = Path(ws_root) / ".specguard" / "experience"
    if not exp_dir.is_dir():
        return []
    meta = _load_meta(exp_dir)
    out = []
    for md in sorted(exp_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        info = meta.get(md.stem, {})
        out.append({
            "token": md.stem,
            "run_id": info.get("run_id", ""),
            "scenario_id": info.get("scenario_id", ""),
            "verdict": info.get("verdict", ""),
            "hit_count": info.get("hit_count", 0),
            "rating": info.get("rating", ""),
            "corrected": info.get("corrected", False),
            "created_at": info.get("created_at", ""),
            "text": md.read_text(encoding="utf-8")[:2000],
        })
    return out
