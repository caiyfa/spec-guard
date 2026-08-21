"""file_preview — 办公文档预览转换器（K-030，零新增依赖）。

xlsx → Markdown 表格（openpyxl read_only）；docx → 纯文本（python-docx）；
pdf → 纯文本（pypdf）。统一出口 preview_text()，供三处复用：
  ① /api/workspace/read-file（FileViewer 弹窗渲染）
  ② routers/agent.py @引用注入（<references> 块）
  ③ mcp_server/tools/spec_reader.py read_spec（Agent 直接读办公文档）

设计约束：
- 全部输出为文本（Markdown 或纯文本），绝不输出二进制/乱码
- 截断保护：行数/页数/总字符上限，防大文件撑爆上下文与弹窗
- 库缺失/解析失败 → 明确错误文本（不抛异常给调用方）
"""

from pathlib import Path

# 单 sheet 最大行数 / PDF 最大页数 / 总字符软上限 / xlsx 文件大小硬上限
_MAX_SHEET_ROWS = 200
_MAX_PDF_PAGES = 30
_MAX_CHARS = 60_000
_MAX_XLSX_BYTES = 30 * 1024 * 1024
_OFFICE_EXTS = {".xlsx", ".docx", ".pdf"}


def is_office_doc(path: Path) -> bool:
    return path.suffix.lower() in _OFFICE_EXTS


def preview_text(path: Path) -> tuple[str, str]:
    """返回 (format, text)：format ∈ {"markdown", "text"}。

    非办公文档由调用方自行按文本读取（本函数不处理）。
    """
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return "markdown", _xlsx_to_markdown(path)
    if ext == ".docx":
        return "text", _docx_to_text(path)
    if ext == ".pdf":
        return "text", _pdf_to_text(path)
    raise ValueError(f"非办公文档类型: {ext}")


def _cell_str(v) -> str:
    if v is None:
        return ""
    s = str(v).replace("\n", " ").replace("|", "\\|").strip()
    return s[:80] + "…" if len(s) > 80 else s


def _xlsx_to_markdown(path: Path) -> str:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return "[xlsx 预览不可用：缺少 openpyxl]"
    # K-035：不能用 read_only=True——read_only 模式信任 sheet XML 声明的 dimension，
    # 非 Excel 生成的导出文件常写错（如 A1:A1），导致整表只读出 1 行 1 列。
    # 普通模式按真实单元格解析，免疫坏 dimension，且能拿到 merged_cells 做回填。
    try:
        if path.stat().st_size > _MAX_XLSX_BYTES:
            return f"[xlsx 文件超过 {_MAX_XLSX_BYTES // 1024 // 1024}MB，不支持预览]"
        wb = load_workbook(str(path), read_only=False, data_only=True)
    except Exception as e:
        return f"[xlsx 解析失败: {e}]"

    parts: list[str] = []
    total = 0
    for ws in wb.worksheets:
        # 合并单元格回填：导出表常用多级合并表头，非左上角单元格值为 None，
        # 不回填则表头/分组列大面积空白，行列对不上（K-035 内容乱根因之二）
        grid: dict[tuple[int, int], object] = {}
        for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if r_idx > _MAX_SHEET_ROWS:
                break
            for c_idx, v in enumerate(row, start=1):
                if v is not None:
                    grid[(r_idx, c_idx)] = v
        for rng in ws.merged_cells.ranges:
            tl = grid.get((rng.min_row, rng.min_col))
            if tl is None:
                continue
            for r in range(rng.min_row, min(rng.max_row, _MAX_SHEET_ROWS) + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    grid.setdefault((r, c), tl)

        rows: list[list[str]] = []
        max_r = min(ws.max_row or 0, _MAX_SHEET_ROWS)
        max_c = ws.max_column or 0
        for r in range(1, max_r + 1):
            cells = [_cell_str(grid.get((r, c))) for c in range(1, max_c + 1)]
            # 跳过全空行
            if any(c for c in cells):
                # 裁剪尾部连续空单元格
                while cells and not cells[-1]:
                    cells.pop()
                rows.append(cells)
        if not rows:
            continue

        width = max(len(r) for r in rows)
        header = rows[0] + [""] * (width - len(rows[0]))
        truncated = (ws.max_row or 0) > _MAX_SHEET_ROWS
        lines = [
            f"## Sheet: {ws.title}（{len(rows)} 行"
            + (f"，已截断至 {_MAX_SHEET_ROWS} 行" if truncated else "")
            + "）",
            "",
            "| " + " | ".join(header) + " |",
            "|" + "---|" * width,
        ]
        for r in rows[1:]:
            r = r + [""] * (width - len(r))
            lines.append("| " + " | ".join(r) + " |")
        block = "\n".join(lines)
        if total + len(block) > _MAX_CHARS:
            parts.append(f"\n[截断] 后续 sheet 省略（总字符超过 {_MAX_CHARS // 1024}KB）")
            break
        parts.append(block)
        total += len(block)

    wb.close()
    if not parts:
        return "[xlsx 文件为空或全部 sheet 无数据]"
    return "\n\n".join(parts)


def _docx_to_text(path: Path) -> str:
    try:
        import docx
    except ImportError:
        return "[docx 预览不可用：缺少 python-docx]"
    try:
        doc = docx.Document(str(path))
    except Exception as e:
        return f"[docx 解析失败: {e}]"

    lines: list[str] = []
    total = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        lines.append(text)
        total += len(text)
        if total > _MAX_CHARS:
            lines.append(f"\n[截断] 总字符超过 {_MAX_CHARS // 1024}KB")
            break
    # 表格内容一并提取（测试用例常放表格里）
    for ti, table in enumerate(doc.tables):
        if total > _MAX_CHARS:
            lines.append(f"\n[截断] 剩余表格省略")
            break
        lines.append(f"\n[表格 {ti + 1}]")
        for row in table.rows[:_MAX_SHEET_ROWS]:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
            total += 1
    return "\n".join(lines) if lines else "[docx 文件无文本内容]"


def _pdf_to_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "[pdf 预览不可用：缺少 pypdf]"
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        return f"[pdf 解析失败: {e}]"

    parts: list[str] = []
    total = 0
    for i, page in enumerate(reader.pages[:_MAX_PDF_PAGES]):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        if not text:
            continue
        block = f"--- 第 {i + 1} 页 ---\n{text}"
        if total + len(block) > _MAX_CHARS:
            parts.append(f"\n[截断] 后续页省略（总字符超过 {_MAX_CHARS // 1024}KB）")
            break
        parts.append(block)
        total += len(block)
    if len(reader.pages) > _MAX_PDF_PAGES:
        parts.append(f"\n[截断] 共 {len(reader.pages)} 页，仅显示前 {_MAX_PDF_PAGES} 页")
    return "\n\n".join(parts) if parts else "[pdf 无可提取文本（可能是扫描件/图片型 PDF）]"
