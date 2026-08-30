/**
 * SheetViewer — xlsx 结构保真预览 + 表格操作（K-036 B 档 / K-040 性能与分析增强）
 *
 * 保真：合并单元格 colspan/rowspan 还原（表头块）、列宽、多 sheet 页签、冻结表头、Excel 行号
 * 操作：点表头排序（数字感知）、表头值列表筛选、全局搜索、拖拽框选复制 TSV、选中统计状态栏
 *
 * K-040 性能设计（大文件不卡）：
 * - 按 sheet 懒解析 + 缓存：打开只解析首个 sheet，切页签才解析目标 sheet（8 sheet 文件打开快 8 倍）
 * - 虚拟滚动：DOM 只挂可视区 ~40 行（此前 1000 行 × N 列 + 框选每次 mouseenter 全表重渲是卡顿主因）
 * - 单 sheet 解析上限 5000 行（防爆内存），超出明确提示
 *
 * 其他设计要点（K-036 沿袭）：
 * - 表头块（顶部连续合并行）保持合并渲染保真；数据区「取消合并」逐行填值——排序/筛选不错位
 * - SheetJS 社区版不读单元格样式（颜色/字体），样式保真属 C 档（Univer）不做
 * - Agent 读文件仍走后端 file_preview 文本转换，本组件只管人看
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import * as XLSX from 'xlsx';

interface SheetData {
  name: string;
  grid: string[][];        // 合并值已回填的完整网格
  headerRows: number;      // 顶部表头块行数（含合并表头）
  merges: XLSX.Range[];    // 仅表头块内的合并（数据区不渲染合并）
  colWidths: number[];     // px
  truncated: boolean;      // 超解析上限
}

interface BodyRow { cells: string[]; no: number }  // no = Excel 原行号（排序/筛选后仍可定位）
interface Sel { r1: number; c1: number; r2: number; c2: number }

const MAX_PARSE_ROWS = 5000;   // 单 sheet 解析上限
const ROW_H = 26;              // 虚拟滚动行高（text-xs + py-1 + border ≈ 26px）
const OVERSCAN = 8;            // 可视区外多渲染行数

function parseSheet(ws: XLSX.WorkSheet, name: string): SheetData {
  const grid = XLSX.utils.sheet_to_json<string[]>(ws, { header: 1, raw: false, defval: '' })
    .map(r => r.map(v => (v == null ? '' : String(v))));
  const truncated = grid.length > MAX_PARSE_ROWS;
  if (truncated) grid.length = MAX_PARSE_ROWS;
  const width = Math.max(1, ...grid.map(r => r.length));
  grid.forEach(r => { while (r.length < width) r.push(''); });

  const allMerges = ws['!merges'] || [];
  // 合并值回填（排序/筛选/复制/统计都基于回填后的网格）
  for (const m of allMerges) {
    const v = grid[m.s.r]?.[m.s.c] ?? '';
    for (let r = m.s.r; r <= Math.min(m.e.r, grid.length - 1); r++)
      for (let c = m.s.c; c <= Math.min(m.e.c, width - 1); c++)
        if (!grid[r][c]) grid[r][c] = v;
  }
  // 表头块 = 从第 1 行起被合并覆盖的连续行（无合并则 1 行表头）
  let headerRows = 1;
  for (const m of allMerges) {
    if (m.s.r < headerRows) headerRows = Math.max(headerRows, m.e.r + 1);
  }
  headerRows = Math.min(headerRows, Math.max(grid.length - 1, 1));
  const headerMerges = allMerges.filter(m => m.e.r < headerRows);

  const colWidths = Array.from({ length: width }, (_, i) => {
    const wch = ws['!cols']?.[i]?.wch;
    return wch ? Math.min(Math.max(Math.round(wch * 7.2), 40), 400) : 0;  // 0 = 自适应
  });
  return { name, grid, headerRows, merges: headerMerges, colWidths, truncated };
}

// 表头块渲染：被合并覆盖的单元格跳过，锚点带 colspan/rowspan
function spanOf(merges: XLSX.Range[], r: number, c: number): { skip: boolean; rowSpan?: number; colSpan?: number } {
  for (const m of merges) {
    if (r >= m.s.r && r <= m.e.r && c >= m.s.c && c <= m.e.c) {
      if (r === m.s.r && c === m.s.c) return { skip: false, rowSpan: m.e.r - m.s.r + 1, colSpan: m.e.c - m.s.c + 1 };
      return { skip: true };
    }
  }
  return { skip: false };
}

function cmpCell(a: string, b: string, dir: 1 | -1): number {
  const na = parseFloat(a), nb = parseFloat(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb)) return (na - nb) * dir;
  return a.localeCompare(b, 'zh-CN') * dir;
}

export default function SheetViewer({ data }: { data: ArrayBuffer }) {
  // 工作簿只 read 一次（轻量）；sheet 内容按需解析（重活）
  const wb = useMemo(() => {
    try { return XLSX.read(data, { type: 'array' }); } catch { return null; }
  }, [data]);
  const sheetCache = useRef(new Map<string, SheetData>());

  const [sheetIdx, setSheetIdx] = useState(0);
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const [filters, setFilters] = useState<Record<number, Set<string>>>({});
  const [filterOpen, setFilterOpen] = useState<number | null>(null);
  const [filterSearch, setFilterSearch] = useState('');
  const [keyword, setKeyword] = useState('');
  const [sel, setSel] = useState<Sel | null>(null);
  const dragging = useRef(false);
  const [copied, setCopied] = useState(false);

  // 虚拟滚动状态
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(600);

  // 切 sheet 重置操作状态（解析结果走缓存，切回不重算）
  useEffect(() => {
    setSort(null); setFilters({}); setFilterOpen(null); setKeyword(''); setSel(null);
    setScrollTop(0);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [sheetIdx]);
  // 全局松开鼠标结束框选
  useEffect(() => {
    const up = () => { dragging.current = false; };
    window.addEventListener('mouseup', up);
    return () => window.removeEventListener('mouseup', up);
  }, []);
  // 视口高度跟踪（虚拟滚动窗口计算）
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    setViewportH(el.clientHeight);
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, [wb]);

  // 当前 sheet：缓存命中直接用，否则现解析并缓存
  const sheet = useMemo(() => {
    if (!wb) return null;
    const name = wb.SheetNames[Math.min(sheetIdx, wb.SheetNames.length - 1)];
    let s = sheetCache.current.get(name);
    if (!s) {
      s = parseSheet(wb.Sheets[name], name);
      sheetCache.current.set(name, s);
    }
    return s;
  }, [wb, sheetIdx]);

  const body: BodyRow[] = useMemo(() =>
    sheet ? sheet.grid.slice(sheet.headerRows).map((cells, i) => ({ cells, no: sheet.headerRows + i + 1 })) : [],
  [sheet]);

  // 搜索 + 筛选 + 排序后的视图行
  const view: BodyRow[] = useMemo(() => {
    let rows = body;
    const kw = keyword.trim().toLowerCase();
    if (kw) rows = rows.filter(r => r.cells.some(c => c.toLowerCase().includes(kw)));
    for (const [colStr, picked] of Object.entries(filters)) {
      const col = Number(colStr);
      if (picked.size > 0) rows = rows.filter(r => picked.has(r.cells[col] ?? ''));
    }
    if (sort) rows = [...rows].sort((a, b) => cmpCell(a.cells[sort.col] ?? '', b.cells[sort.col] ?? '', sort.dir));
    return rows;
  }, [body, keyword, filters, sort]);

  const uniqueValues = useMemo(() => {
    if (filterOpen == null) return [];
    const vals = new Set<string>();
    for (const r of body) vals.add(r.cells[filterOpen] ?? '');
    let arr = [...vals].sort((a, b) => cmpCell(a, b, 1));
    const kw = filterSearch.trim().toLowerCase();
    if (kw) arr = arr.filter(v => v.toLowerCase().includes(kw));
    return arr.slice(0, 200);
  }, [filterOpen, body, filterSearch]);

  // 虚拟滚动窗口
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const endIdx = Math.min(view.length, Math.ceil((scrollTop + viewportH) / ROW_H) + OVERSCAN);
  const windowRows = view.slice(startIdx, endIdx);

  // K-040：选中统计（Excel 状态栏风格——框选即出结果，无需点按钮）
  const selStats = useMemo(() => {
    if (!sel) return null;
    const [ra, rb] = [Math.min(sel.r1, sel.r2), Math.max(sel.r1, sel.r2)];
    const [ca, cb] = [Math.min(sel.c1, sel.c2), Math.max(sel.c1, sel.c2)];
    let count = 0, numCount = 0, sum = 0, min = Infinity, max = -Infinity;
    for (let r = ra; r <= Math.min(rb, view.length - 1); r++) {
      for (let c = ca; c <= cb; c++) {
        const v = (view[r]?.cells[c] ?? '').trim();
        if (!v) continue;
        count++;
        const n = parseFloat(v.replace(/,/g, ''));
        if (!Number.isNaN(n)) {
          numCount++; sum += n;
          if (n < min) min = n;
          if (n > max) max = n;
        }
      }
    }
    return { count, numCount, sum, min, max, avg: numCount ? sum / numCount : 0 };
  }, [sel, view]);

  if (!wb) {
    return <div className="h-full flex items-center justify-center text-fail text-sm">xlsx 解析失败</div>;
  }
  if (!sheet || sheet.grid.length === 0) {
    return <div className="h-full flex items-center justify-center text-gray-500 text-sm">空工作表</div>;
  }

  const headerBlock = sheet.grid.slice(0, sheet.headerRows);
  const lastHeader = sheet.headerRows - 1;
  const activeFilters = Object.values(filters).filter(s => s.size > 0).length;
  const nCols = sheet.grid[0]?.length || 1;

  const clickSort = (col: number) => {
    setSort(prev => !prev || prev.col !== col ? { col, dir: 1 } : prev.dir === 1 ? { col, dir: -1 } : null);
  };

  const inSel = (r: number, c: number) => {
    if (!sel) return false;
    const [ra, rb] = [Math.min(sel.r1, sel.r2), Math.max(sel.r1, sel.r2)];
    const [ca, cb] = [Math.min(sel.c1, sel.c2), Math.max(sel.c1, sel.c2)];
    return r >= ra && r <= rb && c >= ca && c <= cb;
  };

  const copySel = async () => {
    if (!sel) return;
    const [ra, rb] = [Math.min(sel.r1, sel.r2), Math.max(sel.r1, sel.r2)];
    const [ca, cb] = [Math.min(sel.c1, sel.c2), Math.max(sel.c1, sel.c2)];
    const tsv = view.slice(ra, rb + 1).map(r => r.cells.slice(ca, cb + 1).join('\t')).join('\n');
    try {
      await navigator.clipboard.writeText(tsv);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* 剪贴板权限被拒，静默 */ }
  };

  const toggleFilterVal = (col: number, v: string) => {
    setFilters(prev => {
      const cur = new Set(prev[col] ?? []);
      cur.has(v) ? cur.delete(v) : cur.add(v);
      return { ...prev, [col]: cur };
    });
  };

  const fmtNum = (n: number) => Number.isInteger(n) ? String(n) : n.toFixed(2);

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* 工具栏：sheet 页签 + 搜索 + 行数 + 复制 */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border flex-shrink-0 flex-wrap">
        {wb.SheetNames.length > 1 && (
          <div className="flex gap-0.5">
            {wb.SheetNames.map((name, i) => (
              <button key={name} onClick={() => setSheetIdx(i)}
                className={`px-2.5 py-1 text-[11px] rounded-t border-b-2 transition-colors ${
                  i === sheetIdx ? 'text-info border-info bg-info/5' : 'text-gray-500 border-transparent hover:text-gray-300'
                }`}>
                {name}
              </button>
            ))}
          </div>
        )}
        <input
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          placeholder="搜索本表…"
          className="ml-auto bg-surface-2 border border-border rounded px-2 py-1 text-[11px] text-gray-300 placeholder-gray-600 focus:border-info outline-none w-40"
        />
        <span className="text-fs-aux text-gray-600 whitespace-nowrap">
          {view.length === body.length ? `${body.length} 行` : `筛选后 ${view.length} / ${body.length} 行`}
          {sheet.truncated && `（仅解析前 ${MAX_PARSE_ROWS} 行）`}
        </span>
        {sel && (
          <button onClick={copySel}
            className="text-[11px] px-2 py-1 rounded bg-info/10 text-info border border-info/30 hover:bg-info/20">
            {copied ? '✓ 已复制' : '复制选中'}
          </button>
        )}
      </div>

      {/* 表格区（冻结表头 + 虚拟滚动） */}
      <div ref={scrollRef} onScroll={e => setScrollTop((e.target as HTMLDivElement).scrollTop)}
        className="flex-1 min-h-0 overflow-auto">
        <table className="text-xs border-collapse" style={{ tableLayout: sheet.colWidths.some(w => w > 0) ? 'fixed' : 'auto' }}>
          {sheet.colWidths.some(w => w > 0) && (
            <colgroup>
              <col style={{ width: 44 }} />
              {sheet.colWidths.map((w, i) => <col key={i} style={w ? { width: w } : undefined} />)}
            </colgroup>
          )}
          <thead className="sticky top-0 z-10">
            {headerBlock.map((row, r) => (
              <tr key={r}>
                {r === 0 && <th rowSpan={sheet.headerRows} className="px-1 py-1.5 border border-border bg-surface-3 text-gray-600 text-fs-aux font-normal w-11">#</th>}
                {row.map((cell, c) => {
                  const span = spanOf(sheet.merges, r, c);
                  if (span.skip) return null;
                  const isLast = r === lastHeader;
                  return (
                    <th key={c} rowSpan={span.rowSpan} colSpan={span.colSpan}
                      className={`px-2 py-1.5 border border-border text-left font-medium text-gray-300 bg-surface-3 whitespace-nowrap ${isLast ? 'select-none' : ''}`}>
                      {isLast ? (
                        <span className="flex items-center gap-1">
                          <span className="cursor-pointer hover:text-info" onClick={() => clickSort(c)} title="点击排序">
                            {cell || `列${c + 1}`}
                            {sort?.col === c && <span className="text-info">{sort.dir === 1 ? ' ↑' : ' ↓'}</span>}
                          </span>
                          <span className="relative">
                            <button
                              onClick={() => { setFilterOpen(filterOpen === c ? null : c); setFilterSearch(''); }}
                              className={`text-fs-aux px-0.5 rounded ${(filters[c]?.size ?? 0) > 0 ? 'text-info' : 'text-gray-600 hover:text-gray-400'}`}
                              title="筛选">🔽</button>
                            {filterOpen === c && (
                              <span className="absolute left-0 top-full mt-1 z-20 w-48 bg-surface-2 border border-border rounded-lg shadow-xl p-2 block font-normal">
                                <input autoFocus value={filterSearch} onChange={e => setFilterSearch(e.target.value)}
                                  placeholder="搜索值…"
                                  className="w-full bg-surface-3 border border-border rounded px-1.5 py-0.5 text-[11px] text-gray-300 outline-none focus:border-info mb-1" />
                                <span className="flex gap-2 mb-1 text-fs-aux">
                                  <button className="text-info hover:underline"
                                    onClick={() => setFilters(prev => ({ ...prev, [c]: new Set() }))}>清除</button>
                                  <button className="text-gray-500 hover:underline ml-auto" onClick={() => setFilterOpen(null)}>关闭</button>
                                </span>
                                <span className="block max-h-40 overflow-y-auto">
                                  {uniqueValues.map(v => (
                                    <label key={v} className="flex items-center gap-1.5 px-1 py-0.5 text-[11px] text-gray-400 hover:bg-surface-3 rounded cursor-pointer">
                                      <input type="checkbox" checked={filters[c]?.has(v) ?? false}
                                        onChange={() => toggleFilterVal(c, v)} className="accent-info" />
                                      <span className="truncate">{v || '(空)'}</span>
                                    </label>
                                  ))}
                                  {uniqueValues.length === 0 && <span className="block text-fs-aux text-gray-600 px-1">无匹配值</span>}
                                </span>
                              </span>
                            )}
                          </span>
                        </span>
                      ) : (cell || ' ')}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {/* 虚拟滚动：上占位 */}
            {startIdx > 0 && (
              <tr><td colSpan={nCols + 1} style={{ height: startIdx * ROW_H, padding: 0, border: 'none' }} /></tr>
            )}
            {windowRows.map((row, wi) => {
              const r = startIdx + wi;  // view 坐标（排序/筛选后）
              return (
                <tr key={r} className="hover:bg-surface-3/40">
                  <td className="px-1 py-1 border border-border/30 text-gray-600 text-fs-aux text-right select-none bg-surface-2/50 sticky left-0">
                    {row.no}
                  </td>
                  {row.cells.map((cell, c) => (
                    <td key={c}
                      onMouseDown={() => { dragging.current = true; setSel({ r1: r, c1: c, r2: r, c2: c }); }}
                      onMouseEnter={() => { if (dragging.current) setSel(prev => prev ? { ...prev, r2: r, c2: c } : null); }}
                      className={`px-2 py-1 border border-border/30 text-gray-400 cursor-cell select-none whitespace-nowrap overflow-hidden text-ellipsis max-w-[400px] ${
                        inSel(r, c) ? 'bg-info/20 text-gray-200' : ''
                      }`}>
                      {cell}
                    </td>
                  ))}
                </tr>
              );
            })}
            {/* 虚拟滚动：下占位 */}
            {endIdx < view.length && (
              <tr><td colSpan={nCols + 1} style={{ height: (view.length - endIdx) * ROW_H, padding: 0, border: 'none' }} /></tr>
            )}
            {view.length === 0 && (
              <tr><td colSpan={nCols + 1} className="px-3 py-6 text-center text-gray-600">
                {body.length === 0 ? '本 sheet 无数据行' : '无匹配行（调整搜索/筛选条件）'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* K-040：状态栏（选中统计 / 筛选提示） */}
      {(selStats || activeFilters > 0) && (
        <div className="px-3 py-1 border-t border-border text-fs-aux flex-shrink-0 flex items-center gap-3">
          {selStats && (
            <span className="text-gray-400">
              选中 <b className="text-info">{selStats.count}</b> 格
              {selStats.numCount > 0 && (
                <>
                  {' '}· 数值 {selStats.numCount} · 求和 <b className="text-info">{fmtNum(selStats.sum)}</b>
                  {' '}· 平均 {fmtNum(selStats.avg)} · 最大 {fmtNum(selStats.max)} · 最小 {fmtNum(selStats.min)}
                </>
              )}
            </span>
          )}
          {activeFilters > 0 && (
            <span className="text-info ml-auto">
              {activeFilters} 个列筛选生效中
              <button className="ml-2 underline" onClick={() => setFilters({})}>全部清除</button>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
