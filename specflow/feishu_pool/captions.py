"""captions.py — 图片替身文本（飞书知识图谱一期 T8，设计 §9）。

原则：图片从不直接进入 LLM 上下文，由替身文本替代——
- 采集入池：图片默认不下载，正文留占位符 [图片#N]，imgmap 记 media_key；
- 替身回填：视觉模型（二期 transcribe_images）或人工补写，统一走 update_caption；
- LLM 作业输入 = compose_text（正文 + 替身拼装），纯文本模型透明。

imgmap 与原文分离：原文快照保持「拉取时刻冻结」可复算，caption 是派生物。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"\[(图片#\d+)\]")


def compose_text(markdown: str, imgmap: dict) -> str:
    """正文 + 替身文本拼装：[图片#N] → [图片#N: {caption}]。

    仅替换 status=done 且 caption 非空的条目；其余保留原占位符。
    """
    if not imgmap:
        return markdown

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        item = imgmap.get(key) or {}
        caption = str(item.get("caption") or "")
        if item.get("status") == "done" and caption:
            return f"[{key}: {caption}]"
        return m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, markdown)


def update_caption(imgmap_path: Path, placeholder: str, caption: str,
                   by: str = "manual") -> dict:
    """回填替身文本（人工 manual / 视觉模型 vision_llm），幂等。

    Raises:
        KeyError: 占位符不在 imgmap 中
    """
    imgmap_path = Path(imgmap_path)
    imgmap = {}
    if imgmap_path.is_file():
        try:
            imgmap = json.loads(imgmap_path.read_text(encoding="utf-8"))
        except Exception:
            imgmap = {}
    if placeholder not in imgmap:
        raise KeyError(f"占位符不在 imgmap 中: {placeholder}")
    imgmap[placeholder]["caption"] = caption
    imgmap[placeholder]["caption_by"] = by
    imgmap[placeholder]["status"] = "done" if caption else "pending"
    imgmap_path.write_text(json.dumps(imgmap, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return imgmap[placeholder]


def _iter_pending(specflow_emp_base: Path) -> list:
    """扫描材料池全部 imgmap 的 pending 条目 [(imgmap_path, placeholder, media_key)]。"""
    from specflow.feishu_pool.paths import pool_dirs
    out = []
    pool = pool_dirs(specflow_emp_base)
    for sub in ("docs", "chats", "minutes"):
        d = pool[sub]
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.imgmap.json")):
            try:
                imgmap = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for ph, item in imgmap.items():
                if item.get("status") == "pending":
                    out.append((f, ph, str(item.get("media_key") or "")))
    return out


def _download_image(media_key: str) -> bytes:
    """按 media_key 下载图片二进制（lark-cli 只读；二期实装点）。

    docs +media-download（文档图）/ im +messages-resources-download（消息图）。
    统一从 lark_cli.run_lark 走（返回含 base64/文件路径的 payload，
    实测结构以 lark-cli 返回为准微调）。
    """
    import base64
    from specflow.feishu_pool.lark_cli import _run_lark
    payload = _run_lark(["docs", "+media-download", "--media-key", media_key,
                         "--as", "user"])
    data = payload.get("data") or {}
    if data.get("base64"):
        return base64.b64decode(data["base64"])
    if data.get("file"):
        return Path(data["file"]).read_bytes()
    raise ValueError(f"media-download 返回无二进制内容: {media_key}")


def _mark_failed(imgmap_path: Path, placeholder: str, error: str):
    """失败诚实落盘（status=failed + error，可人工改 caption 兜底）。"""
    imgmap_path = Path(imgmap_path)
    try:
        imgmap = json.loads(imgmap_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if placeholder in imgmap:
        imgmap[placeholder]["status"] = "failed"
        imgmap[placeholder]["error"] = error[:200]
        imgmap_path.write_text(json.dumps(imgmap, ensure_ascii=False, indent=2),
                               encoding="utf-8")


def transcribe_images(specflow_emp_base: Path, llm_vision=None,
                      recent_only_days: int = 0) -> dict:
    """视觉转述作业（二期 T-920 实装）。

    扫描材料池 imgmap 的 pending 条目：下载图片 → base64 → vision LLM
    生成 ≤60 字业务描述 → update_caption(by=\"vision_llm\") 回填。

    Args:
        llm_vision: 视觉模型 LLMClient（None = 未配置 → skipped 不阻塞管线）
        recent_only_days: >0 时只处理近 N 天修改的 imgmap（增量自动转用）；
                          0 = 全部（存量手动转用）

    Returns:
        {status: skipped|done, done, failed, total}
    """
    if llm_vision is None:
        return {"status": "skipped", "reason": "未配置视觉模型",
                "done": 0, "failed": 0, "total": 0}
    import base64
    import time as _time
    pendings = _iter_pending(specflow_emp_base)
    if recent_only_days > 0:
        cutoff = _time.time() - recent_only_days * 86400
        pendings = [p for p in pendings
                    if p[0].stat().st_mtime >= cutoff]
    done = failed = 0
    for imgmap_path, ph, media_key in pendings:
        try:
            if not media_key:
                raise ValueError("imgmap 缺 media_key（可能为占位符扫描产物）")
            raw = _download_image(media_key)
            b64 = base64.b64encode(raw).decode("ascii")
            resp = llm_vision.chat([{"role": "user", "content": [
                {"type": "text", "text": "用不超过60字描述这张图的业务内容"
                                           "（架构图/表格/截图的关键信息），"
                                           "直接给描述文本，不要前缀"},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}])
            caption = str(resp.get("content", "")).strip()
            if not caption:
                raise ValueError("vision 模型返回空描述")
            update_caption(imgmap_path, ph, caption, by="vision_llm")
            done += 1
        except Exception as e:
            _mark_failed(imgmap_path, ph, str(e))
            failed += 1
    return {"status": "done", "done": done, "failed": failed,
            "total": len(pendings)}
