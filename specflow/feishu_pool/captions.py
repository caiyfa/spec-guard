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


def transcribe_images(specflow_emp_base: Path, llm_vision=None) -> dict:
    """视觉转述作业（二期接口预留，一期不实现）。

    一期部署不保证多模态模型——llm_vision 为 None 时直接跳过（不阻塞管线）。
    二期接 vision 模型：扫描 imgmap 中 status=pending 条目，下载图片 →
    视觉模型生成 caption → update_caption(by="vision_llm") 回填。
    """
    if llm_vision is None:
        return {"status": "skipped", "reason": "未配置视觉模型（一期接口预留）"}
    raise NotImplementedError("二期接入视觉模型转述")
