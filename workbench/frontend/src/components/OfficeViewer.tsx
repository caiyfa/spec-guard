/**
 * OfficeViewer — 办公文档保真预览入口（K-036 B 档）
 *
 * xlsx → SheetViewer（SheetJS 前端解析：合并/列宽/多 sheet + 排序/筛选/搜索/框选复制）
 * pdf  → blob URL + iframe 原生查看器（缩放/翻页/搜索/打印，替代文本提取）
 * docx → mammoth 转 HTML（标题/表格/加粗/图片保留，替代纯文本提取）
 *
 * 原始字节经 /api/workspace/read-file?raw=true 获取（base64）。
 * Agent 读文件仍走后端 file_preview 文本转换——本组件只管人看的保真预览。
 */

import { lazy, Suspense, useEffect, useState } from 'react';
import { workspaceApi } from '../api';

// SheetJS 体积大（~1MB），按 chunk 懒加载——只在真正打开 xlsx 时才下载
const SheetViewer = lazy(() => import('./SheetViewer'));

function b64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function PdfFrame({ buf, name }: { buf: ArrayBuffer; name: string }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    const u = URL.createObjectURL(new Blob([buf], { type: 'application/pdf' }));
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [buf]);
  if (!url) return null;
  return <iframe src={url} title={name} className="h-full w-full border-0 bg-white" />;
}

function DocxHtml({ buf }: { buf: ArrayBuffer }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        // mammoth 浏览器构建（Vite 打包，避免 node 专属模块）
        const mammoth = await import('mammoth/mammoth.browser');
        const result = await mammoth.convertToHtml({ arrayBuffer: buf });
        if (alive) setHtml(result.value || '<p style="color:#666">（无文本内容）</p>');
      } catch (e: any) {
        if (alive) setError(`docx 解析失败：${e?.message || e}`);
      }
    })();
    return () => { alive = false; };
  }, [buf]);
  if (error) return <div className="h-full flex items-center justify-center text-fail text-fs-lead">{error}</div>;
  if (html == null) return <div className="h-full flex items-center justify-center text-gray-500 text-fs-lead">解析中…</div>;
  return (
    <div className="spec-md h-full overflow-y-auto p-4 text-fs-lead bg-white/5"
      dangerouslySetInnerHTML={{ __html: html }} />
  );
}

export default function OfficeViewer({ path }: { path: string }) {
  const [buf, setBuf] = useState<ArrayBuffer | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    setBuf(null); setError('');
    workspaceApi.readFileRaw(path)
      .then(r => { if (alive) setBuf(b64ToArrayBuffer(r.raw_base64)); })
      .catch(e => { if (alive) setError(e?.message || String(e)); });
    return () => { alive = false; };
  }, [path]);

  if (error) {
    return <div className="h-full flex items-center justify-center text-fail text-fs-lead px-4 text-center">{error}</div>;
  }
  if (!buf) {
    return <div className="h-full flex items-center justify-center text-gray-500 text-fs-lead">读取中…</div>;
  }

  const ext = path.slice(path.lastIndexOf('.')).toLowerCase();
  if (ext === '.xlsx') {
    return (
      <Suspense fallback={<div className="h-full flex items-center justify-center text-gray-500 text-fs-lead">加载表格引擎…</div>}>
        <SheetViewer data={buf} />
      </Suspense>
    );
  }
  if (ext === '.pdf') return <PdfFrame buf={buf} name={path} />;
  if (ext === '.docx') return <DocxHtml buf={buf} />;
  return <div className="h-full flex items-center justify-center text-gray-500 text-fs-lead">不支持的办公文档类型: {ext}</div>;
}
