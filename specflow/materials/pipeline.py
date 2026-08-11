"""pipeline.py — 材料解析管线（M03 §5.3，T-030）。

upload → sniff（magic bytes 格式识别，不信任扩展名）
      → extract（.md/.txt 直读；.docx 解包；.pdf 文本层；扫描件无文本层 → failed）
      → chunk（按章节/段落切分，PRD 按 § 锚点切）

确定性优先：格式识别/指纹/切分为机打；解析产物 _parsed/ 为派生物，可重建。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# ══════════════════════════════════════════════════════════
# sniff：magic bytes 格式识别（不信任扩展名）
# ══════════════════════════════════════════════════════════

_MAGIC_SIGNATURES = {
    b"%PDF-": "pdf",
    b"PK\x03\x04": "docx",      # zip 容器（docx）；md/txt 非 zip
    b"\xef\xbb\xbf": "md",      # UTF-8 BOM
}

# 已知文本扩展名（无 magic 时按扩展名回退；未知二进制 → failed）
_TEXT_EXTS = {".md", ".txt", ".yaml", ".yml", ".json"}


def sniff(content: bytes, filename: str = "") -> Optional[str]:
    """magic bytes 识别格式，返回 fmt（md/docx/pdf/txt）；无法识别返回 None。

    规则：
    - PDF 魔数 %PDF- → pdf
    - zip 容器 PK → docx（.docx 是 zip；xlsx 也是 zip——文件名 .xlsx 不在材料格式白名单）
    - 文本类：UTF-8/ASCII 可解码 → 按扩展名回退（.md/.txt/yaml）
    - 其余 → None（调用方按 failed 处理，不静默降级）
    """
    head = content[:8]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        ext = Path(filename).suffix.lower()
        if ext == ".docx":
            return "docx"
        return None  # 其他 zip 容器（xlsx 等）不在材料白名单
    # 文本类（跳过 BOM）；控制字符占比高判为二进制（x00 等是合法 UTF-8，
    # 仅 decode 成功不够——真实二进制会被误判为 txt）
    body = content[3:] if head.startswith(b"\xef\xbb\xbf") else content
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    ctrl = sum(1 for c in text if ord(c) < 32 and c not in "\t\n\r")
    if ctrl / len(text) > 0.01:
        return None
    ext = Path(filename).suffix.lower()
    if ext in _TEXT_EXTS:
        return ext.lstrip(".")
    return "txt"


# ══════════════════════════════════════════════════════════
# extract：文本抽取
# ══════════════════════════════════════════════════════════

class ExtractError(Exception):
    """解析失败（无文本层/依赖缺失/文件损坏）。"""


def extract(content: bytes, fmt: str) -> str:
    """按格式抽取全文文本。

    Raises:
        ExtractError: 无文本层（扫描件 PDF）/依赖缺失/解析失败——调用方置 status=failed
                      （诚实呈现：不做 OCR 承诺、不静默降级）
    """
    if fmt in ("md", "txt", "yaml"):
        return content.decode("utf-8", errors="replace")
    if fmt == "docx":
        return _extract_docx(content)
    if fmt == "pdf":
        return _extract_pdf(content)
    raise ExtractError(f"不支持的抽取格式: {fmt!r}")


def _extract_docx(content: bytes) -> str:
    """docx 解包 document.xml 抽文本（纯标准库 zip+xml，零新依赖）。"""
    import zipfile
    import xml.etree.ElementTree as ET

    try:
        with zipfile.ZipFile(__import__("io").BytesIO(content)) as zf:
            names = zf.namelist()
            if "word/document.xml" not in names:
                raise ExtractError("docx 缺少 word/document.xml（非有效 Word 文档）")
            xml_bytes = zf.read("word/document.xml")
    except zipfile.BadZipFile:
        raise ExtractError("docx 文件损坏（无法解包）")
    except ExtractError:
        raise
    except Exception as e:
        raise ExtractError(f"docx 解包失败: {e}")

    # XXE 防护：文档内容不可信，含 DTD/实体声明直接拒绝（零依赖，确定性）
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise ExtractError("docx XML 含 DTD/实体声明（疑似 XXE 载荷），已拒绝解析")

    # 段落 + 表格文本（w:p / w:tbl），保留段落边界
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ExtractError(f"docx XML 解析失败: {e}")
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parts: list[str] = []
    for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        texts = [t.text or "" for t in
                 para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        line = "".join(texts).strip()
        if line:
            parts.append(line)
    return "\n".join(parts) if parts else ""


def _extract_pdf(content: bytes) -> str:
    """PDF 文本层抽取（pypdf；扫描件无文本层 → ExtractError，提示人工转录）。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ExtractError("pdf 抽取不可用：缺少 pypdf（新增依赖需过依赖评审）")
    import io
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as e:
        raise ExtractError(f"pdf 解析失败: {e}")
    parts: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        if text:
            parts.append(f"--- 第 {i + 1} 页 ---\n{text}")
    if not parts:
        raise ExtractError("pdf 无文本层（扫描件）——请人工转录后上传，不做 OCR 承诺")
    return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════
# chunk：章节切分
# ══════════════════════════════════════════════════════════

_SECTION_RE = re.compile(r"^#{1,3}\s+(.*)$", re.MULTILINE)       # markdown 标题
_PRD_SECTION_RE = re.compile(r"^§\s*([0-9]+(?:\.[0-9]+)*)[\s:：]*(.*)$", re.MULTILINE)  # §2.7


def chunk(text: str, fmt: str = "md") -> list[dict]:
    """按章节/段落切分，返回 [{section, heading, content}]。

    - md：按 # 标题切；无标题时整体为一段
    - pdf/txt：按「--- 第 N 页 ---」页标切；PRD 类（fmt=pdf 且含 § 锚点）按 § 锚点切
    - docx：按空行分段聚合（上限 50 段，防上下文撑爆）
    """
    if fmt == "md":
        return _chunk_markdown(text)
    if fmt == "pdf":
        if _PRD_SECTION_RE.search(text):
            return _chunk_prd_sections(text)
        return _chunk_pdf_pages(text)
    if fmt == "docx":
        return _chunk_paragraphs(text)
    return [{"section": "all", "heading": "", "content": text}]


def _chunk_markdown(text: str) -> list[dict]:
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return [{"section": "all", "heading": "", "content": text.strip()}]
    chunks = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        chunks.append({"section": f"h{i + 1}", "heading": m.group(1).strip(),
                       "content": body})
    return chunks


def _chunk_pdf_pages(text: str) -> list[dict]:
    pages = re.split(r"--- 第 \d+ 页 ---\n?", text)
    return [{"section": f"page{i + 1}", "heading": "", "content": p.strip()}
            for i, p in enumerate(pages) if p.strip()]


def _chunk_prd_sections(text: str) -> list[dict]:
    """PRD 按 § 锚点切分（coverage_map 的 section 引用依据）。"""
    matches = list(_PRD_SECTION_RE.finditer(text))
    if not matches:
        return _chunk_pdf_pages(text)
    chunks = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunks.append({"section": m.group(1), "heading": m.group(2).strip(),
                       "content": text[start:end].strip()})
    return chunks


def _chunk_paragraphs(text: str, max_blocks: int = 50) -> list[dict]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    chunks = [{"section": f"para{i + 1}", "heading": "",
               "content": b} for i, b in enumerate(blocks[:max_blocks])]
    return chunks or [{"section": "all", "heading": "", "content": text.strip()}]
