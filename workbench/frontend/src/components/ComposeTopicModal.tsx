// ComposeTopicModal.tsx — 勾选原文消息生成话题（T-1002）：
// 左栏已选消息（按时间排序，可移除微调）/ 右栏表单（标题/摘要可预填留空
// 交给 LLM；「补充说明」作为附加上下文拼入 LLM 输入——用户纠正 AI 聚类
// 判断、补充话题背景知识的关键通道）。生成后落草案进入右栏候选段，
// 勾选「生成话题卡」提交入库；md 伪 id 由父层拦截不进入本弹框。

import { useEffect, useMemo, useState } from 'react';
import { feishuPoolApi, type FeishuChatMessage, type FeishuTagRegistry }
  from '../api';
import { MessageBody, useChatMedia, senderColor, fmtMsgTime } from './ChatMessageView';
import { buildTagIndex, tagNormalizeHints } from './topicList';
import ImageLightbox from './ImageLightbox';
import ModelSetupModal from './ModelSetupModal';

export default function ComposeTopicModal({ chatSha8, days, picked, onClose,
                                            onDone, tagReg }: {
  chatSha8: string;
  days: string[];                       // 当前窗口（message_id 定位所属日用）
  picked: FeishuChatMessage[];          // 已勾选消息（父层按 ts 排序传入）
  onClose: () => void;
  onDone: () => void;                   // 生成成功（父层重拉草案+提示）
  tagReg?: FeishuTagRegistry | null;    // tag-taxonomy T1：词表（父层下传）
}) {
  const [msgs, setMsgs] = useState<FeishuChatMessage[]>(picked);
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [keywords, setKeywords] = useState('');
  const [extra, setExtra] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [previewImg, setPreviewImg] = useState<{ url: string; caption: string } | null>(null);
  const [modelSetup, setModelSetup] = useState(false);

  // tag-taxonomy T1：关键词补全 + 别名归一提示（tagReg 缺失诚实降级无提示）
  const tagIdx = useMemo(() => buildTagIndex(tagReg), [tagReg]);
  const tagOptions = useMemo(() => Object.entries(tagReg?.tags || {})
    .filter(([, e]) => e.status === 'active').map(([n]) => n).sort(), [tagReg]);
  const tagHints = useMemo(() => tagNormalizeHints(keywords, tagIdx),
    [keywords, tagIdx]);

  const isMulti = days.length > 1;
  const { imgUrls, imgFailed, captions } = useChatMedia(msgs, chatSha8, days);

  // ESC 关闭（开大图预览时只关预览——弹层嵌套惯例）
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !previewImg && !modelSetup) onClose();
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose, previewImg, modelSetup]);

  const removeMsg = (id: string) =>
    setMsgs(prev => prev.filter(m => m.message_id !== id));

  const generate = async () => {
    if (msgs.length === 0) {
      setErr('至少保留一条原文消息（话题不能零关联）');
      return;
    }
    setBusy(true); setErr('');
    try {
      const kws = keywords.split(/[，,]/).map(s => s.trim()).filter(Boolean);
      await feishuPoolApi.composeTopic({
        chatSha8, days, messageIds: msgs.map(m => m.message_id),
        title, summary, keywords: kws, extraContext: extra,
      });
      onDone();
      onClose();
    } catch (e: any) {
      if (/未配置 text 模型/.test(String(e?.message || ''))) {
        setModelSetup(true);            // T-954 惯例：弹层就地配置，保存后自动重试
      } else {
        setErr(e.message);
      }
    } finally { setBusy(false); }
  };

  const input = 'bg-surface-3 border border-border rounded px-2 py-1.5 text-fs-body text-gray-200 outline-none focus:border-info';
  const btn = 'px-3 py-1.5 rounded text-fs-body font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-6"
      onClick={onClose}>
      <div className="w-[960px] max-w-[96vw] border border-border rounded-lg p-4 bg-surface-2"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-fs-lead font-semibold">按勾选原文生成话题</span>
          <span className="text-fs-aux text-gray-600">
            {days.join(' / ')} · {isMulti ? '跨日窗口' : '单日'}
          </span>
          <button className="ml-auto text-gray-500 hover:text-gray-300"
            onClick={onClose}>✕</button>
        </div>
        {err && <div className="mb-2 px-3 py-2 rounded bg-fail/12 text-fail text-fs-body">{err}</div>}
        <div className="flex gap-3" style={{ height: 'min(64vh, 560px)' }}>
          {/* 左栏：已选消息（按时间序；✕ 移除微调——移除即不再关联） */}
          <div className="w-[46%] shrink-0 flex flex-col border border-border rounded bg-surface-3">
            <div className="px-2 py-1.5 border-b border-border text-fs-body text-gray-400">
              已选原文（{msgs.length} 条；✕ 移除后不再关联本话题）
            </div>
            <div className="flex-1 min-h-0 overflow-auto p-2">
              {msgs.length === 0 ? (
                <div className="text-fs-body text-gray-500">已全部移除——至少保留一条才能生成</div>
              ) : msgs.map((m, i) => (
                <div key={`${m.message_id}-${i}`}
                  className="text-fs-body leading-relaxed px-1.5 py-1 mb-0.5 rounded hover:bg-black/20 group">
                  <div className="flex items-baseline gap-1.5">
                    <span className="font-medium"
                      style={{ color: senderColor(m.sender_id || m.sender_name || '') }}>
                      {m.sender_name || m.sender_id || '?'}
                    </span>
                    <span className="text-fs-aux text-gray-600">{fmtMsgTime(m.ts, isMulti)}</span>
                    <button className="ml-auto text-gray-600 hover:text-fail opacity-0 group-hover:opacity-100 transition-opacity"
                      title="从本话题移除该条"
                      onClick={() => removeMsg(m.message_id)}>✕</button>
                  </div>
                  <div className="text-gray-300">
                    <MessageBody msg={m} imgUrls={imgUrls} imgFailed={imgFailed}
                      captions={captions} highlight={false}
                      onImageClick={(url, caption) => setPreviewImg({ url, caption })} />
                  </div>
                </div>
              ))}
            </div>
          </div>
          {/* 右栏：话题表单（标题/摘要/关键词留空=LLM 生成；补充说明拼入 LLM 输入） */}
          <div className="flex-1 min-w-0 flex flex-col gap-2">
            <label className="text-fs-body text-gray-500">标题（留空由 LLM 生成）</label>
            <input className={input} value={title} maxLength={40}
              onChange={e => setTitle(e.target.value)}
              placeholder="≤20 字；留空自动生成" />
            <label className="text-fs-body text-gray-500">摘要（留空由 LLM 生成）</label>
            <textarea className={input} rows={3} value={summary}
              onChange={e => setSummary(e.target.value)}
              placeholder="≤80 字结论摘要；留空自动生成" />
            <label className="text-fs-body text-gray-500">关键词（逗号分隔，留空由 LLM 生成）</label>
            <input className={input} value={keywords} list="tag-active-compose"
              onChange={e => setKeywords(e.target.value)}
              placeholder="2~5 个；留空自动生成" />
            <datalist id="tag-active-compose">
              {tagOptions.map(n => <option key={n} value={n} />)}
            </datalist>
            {tagHints.length > 0 && (
              <div className="text-fs-aux text-amber-400/90 -mt-1">
                将归一：{tagHints.map(h => `${h.from} → ${h.to}`).join('；')}（词表别名）
              </div>
            )}
            <label className="text-fs-body text-gray-500">
              补充说明（拼入 LLM 输入——纠正归类判断、补充背景，如「这是 817 上线的回归问题」）
            </label>
            <textarea className={input} rows={3} value={extra}
              onChange={e => setExtra(e.target.value)}
              placeholder="可选；将作为附加上下文参与 LLM 生成" />
            <div className="mt-auto flex items-center gap-2 pt-2 border-t border-border">
              <span className="text-fs-aux text-gray-600">
                生成后落右栏「候选段」——勾选「生成话题卡」提交入库
              </span>
              <span className="ml-auto flex gap-2">
                <button className="px-3 py-1.5 rounded text-fs-body text-gray-400 hover:text-gray-200"
                  onClick={onClose}>取消</button>
                <button className={btn} onClick={generate}
                  disabled={busy || msgs.length === 0}>
                  {busy ? '生成中…' : '生成话题'}
                </button>
              </span>
            </div>
          </div>
        </div>
        {previewImg && (
          <ImageLightbox url={previewImg.url} caption={previewImg.caption}
            onClose={() => setPreviewImg(null)} />
        )}
        {modelSetup && (
          <ModelSetupModal purpose="text"
            onClose={() => setModelSetup(false)}
            onConfigured={() => { setModelSetup(false); void generate(); }} />
        )}
      </div>
    </div>
  );
}
