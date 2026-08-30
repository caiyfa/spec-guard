// TopicEditModal.tsx — 话题编辑弹框（T-1001 F3/F4）：
// 左栏原文消息（勾选=关联到本话题）/ 右栏话题内容表单并排——
// 弹框占地大，编辑时可直接对照原文改摘要，也可修正 AI 自动分类
// 关联错的原文（勾选任意消息重新关联，保存时按勾选集合整体替换
// message_ids，并按选中消息换算 window/days）。
// 诚实边界：md 回退伪 id（md-line-N）不可作重关联事实 id——禁改并提示
// 「更新本群」后可用；已入库但快照中找不到的关联如实计数提示。

import { useEffect, useMemo, useState } from 'react';
import { feishuPoolApi, type FeishuTopic, type FeishuChatMessage,
  type FeishuTagRegistry } from '../api';
import { loadChatMessages, isPseudoMessageId, MessageBody, useChatMedia,
  senderColor, fmtMsgTime } from './ChatMessageView';
import { buildTagIndex, tagNormalizeHints } from './topicList';
import ImageLightbox from './ImageLightbox';

// 话题覆盖的日子：跨日卡显式 days；单日卡从 id（tp:{sha8}-{yyyymmdd}-{seq}）取
function topicDays(t: FeishuTopic): string[] {
  if ((t.days || []).length) return t.days;
  const d = String(t.id).match(/-(\d{8})-/)?.[1];
  return d ? [d] : [];
}

// 选中消息 → 后端载荷：window=首末 ts；days=去重日期（ISO ts → yyyymmdd）
// 调用方保证 sel 非空（保存前校验 ≥1 条）
function deriveWindowDays(sel: FeishuChatMessage[]): {
  window: string[]; days: string[];
} {
  const sorted = [...sel].sort((a, b) => a.ts.localeCompare(b.ts));
  const days: string[] = [];
  sorted.forEach(m => {
    const d = (m.ts || '').slice(0, 10).replace(/-/g, '');
    if (d && !days.includes(d)) days.push(d);
  });
  return {
    window: [sorted[0].ts || '', sorted[sorted.length - 1].ts || ''],
    days,
  };
}

export default function TopicEditModal({ topic, onClose, onSaved, tagReg }: {
  topic: FeishuTopic;
  onClose: () => void;
  onSaved: () => void;       // 保存成功/409 后刷新话题清单（父层重拉）
  tagReg?: FeishuTagRegistry | null;  // tag-taxonomy T1：词表（父层下传，不自拉）
}) {
  const [title, setTitle] = useState(topic.title);
  const [summary, setSummary] = useState(topic.summary);
  const [keywords, setKeywords] = useState((topic.keywords || []).join('，'));
  // 分类/优先级：弹框内总是显式选择（旧卡缺省按后端兜底 routine/normal）
  const [category, setCategory] = useState<string>(topic.category || 'routine');
  const [priority, setPriority] = useState<string>(topic.priority || 'normal');
  const [messages, setMessages] = useState<FeishuChatMessage[] | null>(null);
  const [selIds, setSelIds] = useState<Set<string>>(
    () => new Set(topic.message_ids || []));
  const [selTouched, setSelTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [previewImg, setPreviewImg] = useState<{ url: string; caption: string } | null>(null);

  // tag-taxonomy T1：关键词补全（词表 active 主标签）+ 别名归一提示；
  // tagReg 缺失 → 恒等索引 → 无提示，诚实降级
  const tagIdx = useMemo(() => buildTagIndex(tagReg), [tagReg]);
  const tagOptions = useMemo(() => Object.entries(tagReg?.tags || {})
    .filter(([, e]) => e.status === 'active').map(([n]) => n).sort(), [tagReg]);
  const tagHints = useMemo(() => tagNormalizeHints(keywords, tagIdx),
    [keywords, tagIdx]);

  const days = useMemo(() => topicDays(topic), [topic]);
  const isMulti = days.length > 1;

  // 原文加载：话题全部覆盖日（不止当前工作台窗口——跨日卡在单日视图下
  // 也要能看到全部已关联消息，否则保存会静默丢关联）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const r = await loadChatMessages(topic.chat_sha8, days);
      if (!cancelled) setMessages(r.rows);
    })();
    return () => { cancelled = true; };
    // eslint days 引用稳定（useMemo by topic）；topic 切换即重拉
  }, [topic.chat_sha8, days]);

  const { imgUrls, imgFailed, captions } = useChatMedia(messages, topic.chat_sha8, days);

  // md 回退伪 id：不能作为重关联事实 id（保存关联会写入行号伪 id，污染数据）
  const canRelate = !!messages
    && messages.length > 0
    && !messages.some(m => isPseudoMessageId(m.message_id));
  // 已入库关联中不在当前快照里的（重同步后消息漂移）——保存将解除，如实提示
  const missingIds = useMemo(() => {
    if (!messages) return [];
    const loaded = new Set(messages.map(m => m.message_id));
    return (topic.message_ids || []).filter(id => !loaded.has(id));
  }, [messages, topic.message_ids]);

  const toggleSel = (id: string) => {
    setSelTouched(true);
    setSelIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const save = async () => {
    setBusy(true); setErr('');
    try {
      const kws = keywords.split(/[，,]/).map(s => s.trim()).filter(Boolean);
      const payload: Parameters<typeof feishuPoolApi.editTopicCard>[0] = {
        id: topic.id, title, summary, keywords: kws,
        baseRev: topic.rev, category, priority,
      };
      if (selTouched && canRelate) {
        if (selIds.size === 0) {
          setErr('至少勾选一条消息（话题不能零关联）');
          setBusy(false);
          return;
        }
        const sel = (messages || []).filter(m => selIds.has(m.message_id));
        const { window, days: nd } = deriveWindowDays(sel);
        payload.messageIds = sel.map(m => m.message_id);
        payload.window = window;
        payload.days = nd;
      }
      await feishuPoolApi.editTopicCard(payload);
      onSaved();
      onClose();
    } catch (e: any) {
      // 409（已被他人编辑）等如实提示；刷新后重开弹框 rev 对齐可重试
      setErr(e.message);
      onSaved();
    } finally { setBusy(false); }
  };

  // ESC 关闭（弹层惯例；点遮罩同）
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !previewImg) onClose();
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose, previewImg]);

  const input = 'bg-surface-3 border border-border rounded px-2 py-1.5 text-fs-body text-gray-200 outline-none focus:border-info';
  const btn = 'px-3 py-1.5 rounded text-fs-body font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';
  const origin = topic.agent_origin;
  const diff = (cur: string, orig?: string) =>
    orig !== undefined && orig !== cur;
  const selCount = messages
    ? messages.filter(m => selIds.has(m.message_id)).length : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-6"
      onClick={onClose}>
      <div className="w-[1080px] max-w-[96vw] border border-border rounded-lg p-4 bg-surface-2"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-fs-lead font-semibold">编辑话题</span>
          <span className="text-fs-body text-gray-400 truncate" title={topic.title}>{topic.title}</span>
          <span className="text-fs-aux text-gray-600">
            {days.join(' / ')} · {isMulti ? '跨日话题' : '单日'}
          </span>
          <button className="ml-auto text-gray-500 hover:text-gray-300"
            onClick={onClose}>✕</button>
        </div>
        {err && <div className="mb-2 px-3 py-2 rounded bg-fail/12 text-fail text-fs-body">{err}</div>}
        <div className="flex gap-3" style={{ height: 'min(70vh, 640px)' }}>
          {/* 左栏：原文消息（勾选=关联；展示话题覆盖日的全部消息，不限原 window） */}
          <div className="w-[52%] shrink-0 flex flex-col border border-border rounded bg-surface-3">
            <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border text-fs-body">
              <span className="text-gray-400">原文消息</span>
              <span className="text-gray-600">勾选=关联到本话题（已选 {selCount}
                {messages ? ` / ${messages.length}` : ''}）</span>
              {canRelate && (
                <span className="ml-auto flex items-center gap-2">
                  <button className="text-info hover:underline"
                    onClick={() => { setSelTouched(true);
                      setSelIds(new Set((messages || []).map(m => m.message_id))); }}>
                    全选
                  </button>
                  <button className="text-gray-500 hover:text-fail"
                    onClick={() => { setSelTouched(true); setSelIds(new Set()); }}>
                    清空
                  </button>
                  <button className="text-gray-500 hover:text-gray-300"
                    title="恢复为打开弹框时的关联状态"
                    onClick={() => { setSelTouched(false);
                      setSelIds(new Set(topic.message_ids || [])); }}>
                    重置
                  </button>
                </span>
              )}
            </div>
            {!canRelate && messages !== null && (
              <div className="px-2 py-1.5 text-fs-aux text-warn border-b border-border/50">
                {messages.length === 0
                  ? '该话题覆盖日无消息快照——重关联不可用（文本编辑不受影响）'
                  : '旧快照为 md 视图（无精确消息 id），重关联不可用——「↻ 更新本群」重建快照后可用'}
              </div>
            )}
            {missingIds.length > 0 && (
              <div className="px-2 py-1.5 text-fs-aux text-warn border-b border-border/50"
                title={missingIds.join(', ')}>
                {missingIds.length} 条已关联消息未在快照中找到（保存将解除其关联）
              </div>
            )}
            <div className="flex-1 min-h-0 overflow-auto p-2">
              {messages === null ? (
                <div className="text-fs-body text-gray-500">消息加载中…</div>
              ) : messages.length === 0 ? (
                <div className="text-fs-body text-gray-500">窗口内无消息快照</div>
              ) : messages.map((m, i) => {
                const on = selIds.has(m.message_id);
                return (
                  <div key={`${m.message_id}-${i}`}
                    className={`text-fs-body leading-relaxed px-1.5 py-1 mb-0.5 rounded transition-colors ${
                      on ? 'bg-info/20' : 'hover:bg-black/20'}`}
                    onClick={() => canRelate && toggleSel(m.message_id)}>
                    <div className="flex items-baseline gap-1.5">
                      {canRelate && (
                        <input type="checkbox" className="align-middle" checked={on}
                          onClick={e => e.stopPropagation()}
                          onChange={() => toggleSel(m.message_id)} />
                      )}
                      <span className="font-medium"
                        style={{ color: on ? undefined : senderColor(m.sender_id || m.sender_name || '') }}>
                        {m.sender_name || m.sender_id || '?'}
                      </span>
                      <span className="text-fs-aux text-gray-600">{fmtMsgTime(m.ts, isMulti)}</span>
                    </div>
                    <div className={on ? 'text-info' : 'text-gray-300'}>
                      <MessageBody msg={m} imgUrls={imgUrls} imgFailed={imgFailed}
                        captions={captions} highlight={on}
                        onImageClick={(url, caption) => setPreviewImg({ url, caption })} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          {/* 右栏：话题内容表单 */}
          <div className="flex-1 min-w-0 flex flex-col gap-2">
            <label className="text-fs-body text-gray-500">标题</label>
            <input className={input} value={title}
              onChange={e => setTitle(e.target.value)} />
            <label className="text-fs-body text-gray-500">摘要</label>
            <textarea className={input} rows={5} value={summary}
              onChange={e => setSummary(e.target.value)} />
            <label className="text-fs-body text-gray-500">关键词（逗号分隔，2~5 个）</label>
            <input className={input} value={keywords} list="tag-active-edit"
              onChange={e => setKeywords(e.target.value)} />
            <datalist id="tag-active-edit">
              {tagOptions.map(n => <option key={n} value={n} />)}
            </datalist>
            {tagHints.length > 0 && (
              <div className="text-fs-aux text-warn/90 -mt-1">
                将归一：{tagHints.map(h => `${h.from} → ${h.to}`).join('；')}（词表别名）
              </div>
            )}
            <div className="flex gap-2">
              <select className={`${input} flex-1`} value={category}
                onChange={e => setCategory(e.target.value)}
                title="话题分类（五分类）">
                <option value="chat">闲聊</option>
                <option value="routine">沟通</option>
                <option value="requirement">需求</option>
                <option value="test">测试</option>
                <option value="solution">方案</option>
              </select>
              <select className={`${input} flex-1`} value={priority}
                onChange={e => setPriority(e.target.value)}
                title="优先级（信号推导初值，可人工改）">
                <option value="high">高</option>
                <option value="normal">中</option>
                <option value="low">低</option>
              </select>
            </div>
            {origin && (
              <div className="p-2 rounded bg-surface-3/60 border border-border/50">
                <div className="text-fs-aux text-gray-500 mb-0.5">
                  AI 原稿对照（人工修改处标黄，生成优化依据）：
                </div>
                <div className={`text-fs-aux ${diff(title, origin.title) ? 'text-warn' : 'text-gray-500'}`}>
                  题目：{origin.title}
                </div>
                <div className={`text-fs-aux ${diff(summary, origin.summary) ? 'text-warn' : 'text-gray-500'}`}>
                  摘要：{origin.summary}
                </div>
                <div className="text-fs-aux text-gray-600">
                  {origin.model && `模型 ${origin.model} · `}生成于 {origin.generated_at || '—'}
                  {origin.prompt_version && ` · ${origin.prompt_version}`}
                </div>
              </div>
            )}
            <div className="mt-auto flex items-center gap-2 pt-2 border-t border-border">
              <span className="text-fs-aux text-gray-600">
                {selTouched && canRelate
                  ? `关联将更新为勾选的 ${selCount} 条（window/days 随动换算）`
                  : '关联保持不变（仅保存文本字段）'}
              </span>
              <span className="ml-auto flex gap-2">
                <button className="px-3 py-1.5 rounded text-fs-body text-gray-400 hover:text-gray-200"
                  onClick={onClose}>取消</button>
                <button className={btn} onClick={save} disabled={busy}>
                  {busy ? '保存中…' : '保存'}
                </button>
              </span>
            </div>
          </div>
        </div>
      </div>
      {/* 图片大图预览弹层（点击缩略图就地放大；ESC/点遮罩关闭） */}
      {previewImg && (
        <ImageLightbox url={previewImg.url} caption={previewImg.caption}
          onClose={() => setPreviewImg(null)} />
      )}
    </div>
  );
}
