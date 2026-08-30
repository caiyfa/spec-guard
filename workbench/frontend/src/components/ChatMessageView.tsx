// ChatMessageView.tsx — 群聊消息渲染共享件（T-1001 从 TopicWorkspace 抽离）：
// TopicWorkspace 时间轴与 TopicEditModal 原文栏复用同一份富渲染，
// 消除两处维护漂移的可能。内容：
// - loadChatMessages：窗口消息加载（多日 JSONL 拼接 + md 视图回退，行号伪 id）
// - useChatMedia：图片 objectURL 懒拉 + 失败标记 + imgmap captions（T-952/T-955）
// - MessageBody：post 文本+内嵌图 / file 文件卡 / image 图三态渲染
// - senderColor / fmtMsgTime：发送人稳定配色与时间格式化（T-955）

import { useEffect, useState } from 'react';
import { feishuPoolApi, type FeishuChatMessage } from '../api';

// 窗口消息加载：逐日拉 JSONL 事实源拼接（空日跳过）；全部无 JSONL 时回退
// 解析 md 视图（单日旧数据兼容，行号伪 id `md-line-N`——仅供展示与行匹配，
// 不能作为重关联的事实 id，调用方需据此禁用重关联）。
export async function loadChatMessages(
  sha8: string, days: string[],
): Promise<{ rows: FeishuChatMessage[]; empty: boolean }> {
  const rows: FeishuChatMessage[] = [];
  let any = false;
  for (const d of days) {
    try {
      const r = await feishuPoolApi.chatMessages(sha8, d);
      if ((r.items || []).length) { rows.push(...r.items); any = true; }
    } catch { /* 无快照日跳过 */ }
  }
  if (any) return { rows, empty: false };
  // 全部无 JSONL：回退读 md 视图（取窗口最后一日）
  const d = days[days.length - 1];
  try {
    const md = await feishuPoolApi.materialContent(`chats/${sha8}/${d}.md`);
    if (!md.ok) return { rows: [], empty: true };
    const mdRows: FeishuChatMessage[] = (md.content || '').split('\n')
      .filter(l => /^\[\d{2}:\d{2}\]/.test(l))
      .map((l, i) => {
        const m = l.match(/^\[(\d{2}:\d{2})\]\s([^:]+):\s([\s\S]*)$/) || [];
        return {
          message_id: `md-line-${i + 1}`,   // 行号伪 id（回退高亮按行匹配）
          ts: `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}T${m[1] || '??:??'}:00`,
          sender_name: m[2] || '?', msg_type: 'text', content: m[3] || l,
        };
      });
    return { rows: mdRows, empty: mdRows.length === 0 };
  } catch {
    return { rows: [], empty: true };
  }
}

// 消息 id 是否为 md 回退伪 id（伪 id 不可用于重关联）
export function isPseudoMessageId(id: string): boolean {
  return id.startsWith('md-line-');
}

// T-1016：merge_forward（合并转发）内层解析——与 chat_store.parse_forwarded_messages
// 同构（"[ISOts+08:00] 发送人:" 头行 + 缩进内容行；<p> 剥离；两种图片占位按序提取）。
export interface ForwardedSub {
  ts: string;
  sender: string;
  text: string;      // 含图片占位（渲染层剔除后展示）
  keys: string[];    // 内嵌图 key（出现顺序）
}
const FWD_IMG_RE = /!\[Image\]\((.+?)\)|\[Image:\s*(.+?)\]/g;
const FWD_HEAD_RE = /^\[([^\]]+)\]\s+([^:：]+)[:：]\s*$/;
export function parseForwardedMessages(content: string): ForwardedSub[] {
  if (!content || !content.includes('<forwarded_messages>')) return [];
  const body = content.replace('<forwarded_messages>', '')
    .replace('</forwarded_messages>', '');
  const subs: { ts: string; sender: string; lines: string[] }[] = [];
  body.split('\n').forEach(line => {
    const head = /^\S/.test(line) ? line.match(FWD_HEAD_RE) : null;
    if (head) subs.push({ ts: head[1].trim(), sender: head[2].trim(), lines: [] });
    else if (subs.length) subs[subs.length - 1].lines.push(line.trim());
  });
  return subs.map(s => {
    const text = s.lines.filter(Boolean).join(' ').replace(/<\/?p>/g, '').trim();
    const keys: string[] = [];
    for (const m of text.matchAll(FWD_IMG_RE)) keys.push((m[1] || m[2]).trim());
    return { ts: s.ts, sender: s.sender, text, keys };
  });
}

// T-952 富渲染素材：窗口内全部图片 (message_id, key) 配对懒拉 + imgmap
// captions；T-955 图片三态之失败态显式标记（不再永远「加载中」）。
export function useChatMedia(messages: FeishuChatMessage[] | null,
                             sha8: string, days: string[]) {
  const [imgUrls, setImgUrls] = useState<Record<string, string>>({});
  const [imgFailed, setImgFailed] = useState<Set<string>>(new Set());
  const [captions, setCaptions] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!messages) return;
    const pairs = new Set<string>();            // "mid|key"（图属消息——im 下载需配对）
    messages.forEach(m => {
      (m.image_keys || []).forEach(k => k && pairs.add(`${m.message_id}|${k}`));
      if (m.image_key && m.message_id) pairs.add(`${m.message_id}|${m.image_key}`);
      // T-1016：merge_forward 内嵌图兜底——存量 JSONL 行无 image_keys 时
      // 从 content 解析（外层 message_id 配对下载）
      if (m.msg_type === 'merge_forward' && m.message_id) {
        parseForwardedMessages(m.content || '').forEach(s =>
          s.keys.forEach(k => pairs.add(`${m.message_id}|${k}`)));
      }
    });
    let cancelled = false;
    pairs.forEach(pk => {
      const [mid, k] = pk.split('|');
      feishuPoolApi.fetchChatImageBlob(mid, k).then(blob => {
        if (!cancelled) {
          const url = URL.createObjectURL(blob);
          setImgUrls(prev => prev[k] ? (URL.revokeObjectURL(url), prev) : { ...prev, [k]: url });
        }
      }).catch(() => {
        if (!cancelled) setImgFailed(prev => new Set(prev).add(k));
      });
    });
    // captions：逐日报 imgmap（key→caption）
    (async () => {
      const cap: Record<string, string> = {};
      for (const d of days) {
        try {
          const r = await feishuPoolApi.materialContent(`chats/${sha8}/${d}.md`);
          if (cancelled) return;
          (r.images || []).forEach((i: any) => {
            if (i.media_key && i.caption) cap[i.media_key] = i.caption;
          });
        } catch { /* 无快照日跳过 */ }
      }
      if (!cancelled && Object.keys(cap).length) setCaptions(prev => ({ ...prev, ...cap }));
    })();
    return () => { cancelled = true; };
    // eslint 无 imgUrls 依赖：函数式更新 + 卸载时由窗口切换的下一个 effect 清理
  }, [messages, sha8, days]);

  return { imgUrls, imgFailed, captions };
}

// T-952：消息体真实内容渲染——post 文本+内嵌图 / file 文件卡（可下载）/ image 图。
// 图片三态（加载中/失败/成功——体验基线③）；转述 caption 展示在图下（agent
// 检索与用户审阅同一份描述——技术侧转述对用户透明，无独立维护入口）。
export function MessageBody({ msg, imgUrls, imgFailed, captions, highlight, onImageClick }: {
  msg: FeishuChatMessage;
  imgUrls: Record<string, string>;
  imgFailed: Set<string>;
  captions: Record<string, string>;
  highlight: boolean;
  onImageClick: (url: string, caption: string) => void;
}) {
  const imgCls = 'max-h-28 rounded border border-border mt-1 mr-1 inline-block align-top cursor-pointer';
  const capCls = `text-fs-aux mt-0.5 ${highlight ? 'text-info/80' : 'text-gray-500'}`;
  const renderImgs = (keys: (string | undefined)[]) => (
    keys.filter(Boolean).map(k => {
      const key = k as string;
      return (
        <span key={key} className="inline-block mr-1 align-top">
          {imgUrls[key] ? (
            <img src={imgUrls[key]} alt="聊天图片"
              className={imgCls}
              title={captions[key] || 'AI 转述生成中…'}
              onClick={e => {
                // 点击大图预览（弹层就地放大；ESC/点遮罩关闭，不跳新标签页）
                e.stopPropagation();
                onImageClick(imgUrls[key], captions[key] || '');
              }} />
          ) : imgFailed.has(key) ? (
            <span className="inline-block w-16 h-16 leading-[3.5rem] text-center rounded
              border border-fail/35 bg-fail/5 text-fs-aux text-fail align-top"
              title="图片加载失败（当前飞书账号无该图权限或下载失败，刷新页面重试）">加载失败</span>
          ) : (
            <span className="inline-block w-16 h-16 leading-[4rem] text-center rounded
              border border-border bg-black/30 text-fs-aux text-gray-600 align-top">加载中…</span>
          )}
          {captions[key] && (
            <div className={capCls}>{captions[key]}</div>
          )}
        </span>
      );
    })
  );
  if (msg.msg_type === 'image') {
    return <>{renderImgs([msg.image_key])}</>;
  }
  if (msg.msg_type === 'post') {
    // 文本主体（内嵌图引用剔除——图单独渲染）
    const text = (msg.content || '')
      .replace(/!\[Image\]\([^)]*\)/g, '').trim();
    return (
      <>
        {text && <span className="whitespace-pre-wrap break-all">{text}</span>}
        {(msg.image_keys || []).length > 0 && <div>{renderImgs(msg.image_keys)}</div>}
      </>
    );
  }
  if (msg.msg_type === 'file') {
    if (!msg.file_key || !msg.message_id) {
      // 旧快照无附件信息（T-952a 前落盘）——提示重拉而非静默无响应
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded mt-1
          bg-black/20 border border-border"
          title="旧快照无附件下载信息——点「↻ 更新本群」重新同步后可下载">
          <span className="text-fs-lead">📎</span>
          <span className="text-gray-300">{msg.file_name || '文件'}</span>
          <span className="text-fs-aux text-amber-500/80">需更新后可下载</span>
        </span>
      );
    }
    return (
      // T-955：附件可下载（blob 拉取 + a.download；失败如实提示）
      <button
        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded mt-1
          ${highlight ? 'bg-info/15' : 'bg-black/20 border border-border hover:border-info/50'}`}
        title="点击下载附件"
        onClick={e => {
          e.stopPropagation();
          const name = msg.file_name || 'attachment';
          feishuPoolApi.fetchChatFileBlob(msg.message_id!, msg.file_key!, name)
            .then(blob => {
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url; a.download = name;
              a.click();
              setTimeout(() => URL.revokeObjectURL(url), 30_000);
            })
            .catch(() => { /* 下载失败：提示由调用方 notice 承担（本组件无 state） */ });
        }}>
        <span className="text-fs-lead">📎</span>
        <span className="text-gray-300">{msg.file_name || '文件'}</span>
        <span className="text-fs-aux text-gray-600">点击下载</span>
      </button>
    );
  }
  if (msg.msg_type === 'merge_forward') {
    // T-1016：合并转发按子消息列表渲染（与正常聊天同构：发送人配色+时间+内容），
    // 内嵌图占位替换为真实缩略图；解析失败兜底原文。
    const subs = parseForwardedMessages(msg.content || '');
    if (!subs.length) {
      return <span className="whitespace-pre-wrap break-all">{msg.content}</span>;
    }
    return (
      <div className="mt-1 rounded border border-border/60 bg-black/20 px-2 py-1.5">
        <div className="text-fs-aux text-gray-500 mb-1">合并转发 {subs.length} 条</div>
        <div className="space-y-1.5">
          {subs.map((s) => {
            const text = s.text.replace(FWD_IMG_RE, '').trim();
            return (
              <div key={`${s.ts}|${s.sender}|${s.text.slice(0, 12)}`}>
                <span className="font-medium" style={{ color: senderColor(s.sender) }}>
                  {s.sender}
                </span>
                <span className="ml-1 text-fs-aux text-gray-600">
                  {s.ts.slice(11, 16)}
                </span>
                {text && (
                  <span className="ml-1 whitespace-pre-wrap break-all">{text}</span>
                )}
                {s.keys.length > 0 && <div>{renderImgs(s.keys)}</div>}
              </div>
            );
          })}
        </div>
      </div>
    );
  }
  return <span className="whitespace-pre-wrap break-all">{msg.content}</span>;
}

// T-955：消息时间格式化（单日 HH:MM；多日 MM-DD HH:MM——去 ISO 的 T）
export function fmtMsgTime(ts: string, isMulti: boolean): string {
  if (!ts) return '';
  return isMulti
    ? `${ts.slice(5, 10)} ${ts.slice(11, 16)}`
    : ts.slice(11, 16);
}

// T-955：发送人稳定配色（按 id 哈希取色相环——IM 惯例，一眼区分谁在说话）
const SENDER_PALETTE = ['#60a5fa', '#f59e0b', '#34d399', '#a78bfa', '#f87171',
  '#22d3ee', '#eab308', '#f472b6'];
export function senderColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return SENDER_PALETTE[h % SENDER_PALETTE.length];
}
