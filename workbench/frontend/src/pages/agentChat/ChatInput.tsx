import { useEffect, useMemo, useRef, useState } from 'react';
import { draftsApi, scenarioApi, specflowApi, workspaceApi } from '../../api';
import type { DraftItem, ModelConfig, ScenarioMeta } from '../../api';
import type { ChatReference } from './types';

interface SlashCommand {
  cmd: string;
  label: string;
  desc: string;
  type: 'skill' | 'mode' | 'action';
  skillName?: string;   // 技能名（cmd 与技能名不一致时指定，如 /dag → dag-orchestration）
}

const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: '/generate-scenario', label: '场景生成技能', desc: '使用场景生成技能分析需求', type: 'skill' },
  { cmd: '/validate-conformance', label: '合规校验技能', desc: '校验场景 YAML 格式合规性', type: 'skill' },
  { cmd: '/debug-failure', label: '失败分析技能', desc: '分析运行报告中的失败场景', type: 'skill' },
  { cmd: '/dag', label: 'DAG 编排', desc: '对话中编排场景依赖（建议/加边/删边/复核）', type: 'skill', skillName: 'dag-orchestration' },
  { cmd: '/new', label: '新会话', desc: '开始新的对话会话', type: 'action' },
  { cmd: '/clear', label: '清空对话', desc: '清空当前消息列表', type: 'action' },
  { cmd: '/undo', label: '撤销写入', desc: '撤销最后一次草稿写入（从 .bak 恢复）', type: 'action' },
  { cmd: '/export', label: '导出会话', desc: '导出当前会话为 JSON 文件', type: 'action' },
];

// ── @候选类型（ChatInput 内部使用）──
interface AtCandidate { type: 'info_pack' | 'file' | 'draft'; id: string; label: string; hint: string }

// ── ChatInput 组件（独立子组件，打字不触发父组件重渲染）──
interface ChatInputProps {
  wsState: 'connecting' | 'open' | 'closed';
  loading: boolean;
  models: ModelConfig[];
  currentModelId: string;
  onSend: (text: string, references: ChatReference[]) => boolean;  // 返回是否真正发出（ true 时输入框清空）
  onStop: () => void;
  onNewSession: () => void;
  onClearMessages: () => void;
  onExportSession: () => void;
  onModelChange: (id: string) => void;
  quickText?: string;             // S0.6：外部注入文本（如「让 Agent 修复」带失败原因），注入后自动清空
  onQuickTextHandled?: () => void;
  sessionId: string;              // T-933：材料上传按会话反查绑定面试（sf_interviews）
  onMaterialUploaded?: () => void;  // T-933：上传成功后展开材料页签刷新
}

export function ChatInput({
  wsState, loading, models, currentModelId,
  onSend, onStop, onNewSession, onClearMessages, onExportSession, onModelChange,
  quickText, onQuickTextHandled, sessionId, onMaterialUploaded,
}: ChatInputProps) {
  const [input, setInput] = useState('');
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashQuery, setSlashQuery] = useState('');
  const [slashIndex, setSlashIndex] = useState(0);

  // S0.6：外部注入文本（足迹卡「让 Agent 修复」→ 失败原因带进对话），用户确认后发送
  useEffect(() => {
    if (!quickText) return;
    setInput(quickText);
    inputRef.current?.focus();
    onQuickTextHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quickText]);
  const [atOpen, setAtOpen] = useState(false);
  const [atQuery, setAtQuery] = useState('');
  const [atIndex, setAtIndex] = useState(0);
  const [atMetas, setAtMetas] = useState<ScenarioMeta[]>([]);
  const [atDrafts, setAtDrafts] = useState<DraftItem[]>([]);
  const [atFileResults, setAtFileResults] = useState<{ path: string; preview: string }[]>([]);
  const [references, setReferences] = useState<ChatReference[]>([]);
  const [attaching, setAttaching] = useState(false);
  const attachInputRef = useRef<HTMLInputElement>(null);
  // T-933：材料上传入口（S3 端点，区别于 📎 信息包附件）
  const matInputRef = useRef<HTMLInputElement>(null);
  const [matNotice, setMatNotice] = useState<{ text: string; error: boolean } | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 斜杠命令过滤
  const filteredCommands = useMemo(() => {
    if (!slashQuery) return SLASH_COMMANDS;
    return SLASH_COMMANDS.filter(c => c.cmd.includes(slashQuery) || c.label.includes(slashQuery));
  }, [slashQuery]);

  // @候选
  const atCandidates = useMemo<AtCandidate[]>(() => {
    const q = atQuery.toLowerCase();
    const list: AtCandidate[] = [];
    for (const m of atMetas) {
      if (!q || m.id.toLowerCase().includes(q) || (m.name || '').toLowerCase().includes(q)) {
        list.push({ type: 'info_pack', id: m.id, label: `📦 ${m.name || m.id}`, hint: `信息包 · ${m.info_pack?.length || 0} 文件` });
      }
    }
    for (const d of atDrafts) {
      if (!q || d.filename.toLowerCase().includes(q) || (d.title || '').toLowerCase().includes(q)) {
        list.push({ type: 'draft', id: d.filename, label: `📝 ${d.title || d.filename}`, hint: `草稿 · ${d.filename}` });
      }
    }
    for (const f of atFileResults) {
      list.push({ type: 'file', id: f.path, label: `📄 ${f.path}`, hint: '工作区文件' });
    }
    return list.slice(0, 20);
  }, [atMetas, atDrafts, atFileResults, atQuery]);

  // 输入框高度自适应
  useEffect(() => {
    const ta = inputRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 128)}px`;
  }, [input]);

  // @候选懒加载
  const atLoadedRef = useRef(false);
  useEffect(() => {
    if (!atOpen || atLoadedRef.current) return;
    atLoadedRef.current = true;
    scenarioApi.listMeta().then(r => setAtMetas(r.metas || [])).catch(() => {});
    draftsApi.list().then(r => setAtDrafts(r.drafts || [])).catch(() => {});
  }, [atOpen]);

  // @文件搜索（防抖，≥2 字符）
  useEffect(() => {
    if (!atOpen || atQuery.length < 2) { setAtFileResults([]); return; }
    const timer = setTimeout(() => {
      workspaceApi.search(atQuery)
        .then(r => setAtFileResults((r.results || []).map(x => ({ path: x.path, preview: x.preview }))))
        .catch(() => setAtFileResults([]));
    }, 300);
    return () => clearTimeout(timer);
  }, [atOpen, atQuery]);

  const handleInputChange = (value: string) => {
    setInput(value);
    if (value.startsWith('/') && !value.includes(' ')) {
      setSlashOpen(true); setSlashQuery(value); setSlashIndex(0);
    } else {
      setSlashOpen(false);
    }
    const atMatch = value.match(/@([^\s@]*)$/);
    if (atMatch) {
      setAtOpen(true); setAtQuery(atMatch[1]); setAtIndex(0);
    } else {
      setAtOpen(false);
    }
  };

  const handleAtSelect = (c: { type: 'info_pack' | 'file' | 'draft'; id: string }) => {
    setInput(prev => prev.replace(/@[^\s@]*$/, ''));
    setAtOpen(false);
    if (c.type === 'info_pack') {
      const m = atMetas.find(x => x.id === c.id);
      setReferences(prev => [
        ...prev.filter(r => r.type !== 'info_pack'),
        { type: 'info_pack', path: c.id, sha: '', label: m?.name || c.id },
      ]);
    } else {
      setReferences(prev => prev.some(r => r.type === c.type && r.path === c.id)
        ? prev : [...prev, { type: c.type, path: c.id, sha: '' }]);
    }
    inputRef.current?.focus();
  };

  const handleSlashSelect = (cmd: SlashCommand) => {
    setSlashOpen(false); setInput('');
    if (cmd.type === 'action') {
      if (cmd.cmd === '/new') { onNewSession(); }
      else if (cmd.cmd === '/clear') { onClearMessages(); }
      else if (cmd.cmd === '/undo') {
        onSend('请使用 undo_draft 工具撤销最后一次草稿写入。如果不知道文件名，请先查看 drafts 目录。', []);
      } else if (cmd.cmd === '/export') { onExportSession(); }
    } else if (cmd.type === 'skill') {
      const skillName = cmd.skillName || cmd.cmd.replace('/', '');
      setInput(`请使用 ${skillName} 技能${skillName === 'dag-orchestration' ? '编排场景依赖' : ''}：`);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (atOpen) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setAtIndex(i => Math.min(i + 1, atCandidates.length - 1)); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setAtIndex(i => Math.max(i - 1, 0)); return; }
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (atCandidates[atIndex]) handleAtSelect(atCandidates[atIndex]); return; }
      if (e.key === 'Escape') { e.preventDefault(); setAtOpen(false); return; }
    }
    if (slashOpen) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setSlashIndex(i => Math.min(i + 1, filteredCommands.length - 1)); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSlashIndex(i => Math.max(i - 1, 0)); return; }
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (filteredCommands[slashIndex]) handleSlashSelect(filteredCommands[slashIndex]); return; }
      if (e.key === 'Escape') { e.preventDefault(); setSlashOpen(false); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
  };

  // 发送成功（onSend 返回 true）才清空输入框与引用 chips——发送被拒（断连/加载中）时保留草稿；
  // 引用是「随一条消息消费」的一次性载体（附件内容随当轮 user message 注入），不清空会
  // 导致 chip 常驻输入区、后续每轮消息重复携带并触发后端重复读取注入（会话 20260825_151821_3178914e）
  const doSend = () => {
    if (onSend(input.trim(), references)) { setInput(''); setReferences([]); }
  };

  const handleAttachFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setAttaching(true);
    try {
      const meta = await scenarioApi.autoCreateInfoPack(Array.from(files));
      setReferences(prev => [
        ...prev.filter(r => r.type !== 'info_pack'),
        { type: 'info_pack', path: meta.id, sha: '', label: `${meta.name}（${(meta.info_pack || []).length} 个文件）` },
      ]);
      setAtMetas(prev => [meta, ...prev.filter(m => m.id !== meta.id)]);
    } catch {
      // 附件上传失败静默处理
    } finally {
      setAttaching(false);
      if (attachInputRef.current) attachInputRef.current.value = '';
    }
  };

  // T-933：对话内材料上传——按会话反查绑定面试（sf_interviews），走 S3 既有上传
  // 端点；成功挂 material 引用卡片随下一条消息进 references（Agent 用 read_material 读）
  const handleMaterialFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (!sessionId) {
      setMatNotice({ text: '会话尚未建立——先发送一条消息（选定用途）再上传材料', error: false });
      return;
    }
    setAttaching(true); setMatNotice(null);
    try {
      const dock = await specflowApi.gateDock({ session_id: sessionId });
      const iv = dock.interview;
      if (!iv) {
        setMatNotice({ text: '当前会话未开启需求面试——材料随面试归档，先在对话中开标（如「开启需求面试」）再上传', error: false });
        return;
      }
      const failed: string[] = [];
      let okCount = 0;
      for (const f of Array.from(files)) {
        try {
          const r = await specflowApi.uploadMaterial(iv.iv_id, f);
          setReferences(prev => prev.some(x => x.type === 'material' && x.path === r.material.mid)
            ? prev
            : [...prev, { type: 'material', path: r.material.mid,
                          sha: r.material.sha256_12 || '', label: r.material.filename }]);
          okCount += 1;
        } catch (e: any) {
          failed.push(`${f.name}: ${e.message}`);
        }
      }
      if (failed.length) {
        setMatNotice({ text: `上传失败 ${failed.length} 个——${failed.join('；')}`, error: true });
      } else if (okCount > 0) {
        setMatNotice({ text: `已上传 ${okCount} 个材料并挂入引用（随下一条消息进入对话上下文）`, error: false });
        onMaterialUploaded?.();
      }
    } catch (e: any) {
      setMatNotice({ text: `材料上传失败: ${e.message}`, error: true });
    } finally {
      setAttaching(false);
      if (matInputRef.current) matInputRef.current.value = '';
    }
  };

  return (
    <div className="flex-shrink-0 border-t border-border p-3 relative">
      {/* slash 命令弹出层 */}
      {slashOpen && filteredCommands.length > 0 && (
        <div className="absolute bottom-full left-3 right-3 mb-1 bg-surface-2 border border-border rounded-lg shadow-xl max-h-60 overflow-y-auto z-10">
          {filteredCommands.map((c, i) => (
            <button key={c.cmd} onClick={() => handleSlashSelect(c)}
              className={`w-full text-left px-3 py-2 flex items-center gap-2 transition-colors ${
                i === slashIndex ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
              }`}>
              <span className="font-mono text-xs text-info/70">{c.cmd}</span>
              <span className="text-xs">{c.label}</span>
              <span className="text-[10px] text-gray-600 ml-auto">{c.desc}</span>
            </button>
          ))}
        </div>
      )}

      {/* @引用候选层 */}
      {atOpen && atCandidates.length > 0 && (
        <div className="absolute bottom-full left-3 right-3 mb-1 bg-surface-2 border border-border rounded-lg shadow-xl max-h-60 overflow-y-auto z-10">
          {atCandidates.map((c, i) => (
            <button key={`${c.type}:${c.id}`} onClick={() => handleAtSelect(c)}
              className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
                i === atIndex ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
              }`}>
              <span className="text-xs truncate">{c.label}</span>
              <span className="text-[10px] text-gray-600 ml-auto flex-shrink-0">{c.hint}</span>
            </button>
          ))}
        </div>
      )}

      {/* T-933：材料上传反馈（就地提示不踢人；失败红/引导黄） */}
      {matNotice && (
        <div className={`mb-2 px-2 py-1 rounded text-[11px] ${
          matNotice.error ? 'bg-red-500/10 text-red-400' : 'bg-amber-500/10 text-amber-300'}`}>
          {matNotice.text}
          <button className="ml-2 text-gray-500 hover:text-gray-300"
            onClick={() => setMatNotice(null)}>✕</button>
        </div>
      )}

      {/* 已选引用 chips */}
      {references.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {references.map((r, i) => (
            <span key={`${r.type}:${r.path}`}
              className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-info/10 text-info border border-info/30 font-mono">
              {r.type === 'info_pack' ? '📦' : r.type === 'draft' ? '📝' : r.type === 'material' ? '🧾' : '📄'} {r.label || r.path}
              <button onClick={() => setReferences(prev => prev.filter((_, j) => j !== i))}
                className="text-info/60 hover:text-fail">✕</button>
            </span>
          ))}
        </div>
      )}

      {/* 输入框 + 附件/材料 + 发送/停止按钮 */}
      <div className="flex gap-2 items-end">
        <input
          ref={attachInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={e => handleAttachFiles(e.target.files)}
        />
        <button
          onClick={() => attachInputRef.current?.click()}
          disabled={attaching || loading || wsState !== 'open'}
          title="上传附件（自动创建信息包并关联到本轮对话）"
          className="w-10 h-10 flex-shrink-0 bg-surface-2 border border-border text-gray-400 rounded-full flex items-center justify-center hover:text-info hover:border-info/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {attaching ? <span className="animate-spin text-sm">⏳</span> : <span className="text-lg">📎</span>}
        </button>
        {/* T-933：材料上传（进当前面试材料池，Agent 可 read_material 读取） */}
        <input
          ref={matInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={e => handleMaterialFiles(e.target.files)}
        />
        <button
          onClick={() => matInputRef.current?.click()}
          disabled={attaching || loading || wsState !== 'open'}
          title="上传材料（进入当前需求面试的材料池，随引用进入对话，Agent 可用 read_material 读取原文）"
          className="w-10 h-10 flex-shrink-0 bg-surface-2 border border-border text-gray-400 rounded-full flex items-center justify-center hover:text-info hover:border-info/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {attaching ? <span className="animate-spin text-sm">⏳</span> : <span className="text-lg">🧾</span>}
        </button>
        <textarea
          ref={inputRef}
          value={input}
          onChange={e => handleInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={wsState === 'open' ? '输入消息... (Enter 发送, / 命令, @ 引用)' : 'WebSocket 未连接'}
          rows={1}
          className="flex-1 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none resize-none max-h-32"
          disabled={loading || wsState !== 'open'}
        />
        {loading ? (
          <button
            onClick={onStop}
            title="打断会话"
            className="w-10 h-10 flex-shrink-0 bg-red-600 text-white rounded-full flex items-center justify-center hover:bg-red-500 transition-colors"
          >
            <span className="text-lg">■</span>
          </button>
        ) : (
          <button
            onClick={doSend}
            disabled={!input.trim() || wsState !== 'open'}
            className="w-10 h-10 flex-shrink-0 bg-info text-white rounded-full flex items-center justify-center hover:bg-info/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ↑
          </button>
        )}
      </div>

      {/* 底部模型选择器 */}
      <div className="flex items-center gap-2 mt-2">
        {models.length > 0 && (
          <select
            value={currentModelId}
            onChange={e => onModelChange(e.target.value)}
            className="bg-surface-2 border border-border rounded px-2 py-0.5 text-[10px] text-gray-400 font-mono"
          >
            {models.map(m => (
              <option key={m.id} value={m.id}>
                {m.is_default ? '★ ' : ''}{m.name || m.model}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
