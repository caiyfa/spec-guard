import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { draftsApi } from '../../api';
import type { DraftItem, TrialRunResult, ValidateReport } from '../../api';

// ── 草稿产物区（K-xxx：草稿评审融合进 Agent 对话——写入草稿后直接在右侧校验/试跑/入库） ──
interface DraftCardState {
  validate?: ValidateReport;
  validating?: boolean;
  trial?: TrialRunResult;
  running?: boolean;
  promotedTo?: string;   // 已入库目标路径（入库后草稿已移入场景库，drafts 下不再存在）
  scenarioId?: string;   // 入库成功时返回的场景 ID（refresh 后 drafts 列表已无此草稿，需本地留存）
  discarded?: boolean;
}

export function DraftArtifactsPanel({ draftFiles, onViewFile, onError }: {
  draftFiles: string[];                          // 本次会话 Agent 写入的草稿文件名（write_draft 检测）
  onViewFile: (path: string, kind?: 'file' | 'draft') => void;
  onError: (msg: string) => void;
}) {
  const navigate = useNavigate();
  const [metaMap, setMetaMap] = useState<Record<string, DraftItem>>({});
  const [modules, setModules] = useState<string[]>([]);
  // K-xxx：草稿依赖建议计数（suggest_deps 确定性引擎，草稿评审页可一键采纳）
  const [suggCount, setSuggCount] = useState<Record<string, number>>({});
  const [state, setState] = useState<Record<string, DraftCardState>>({});
  // K-xxx：drafts 列表查不到的文件（入库/废弃/刷新后）——用 conflict 预检判定去向：
  // ID 命中场景库 = 已入库（本地 promotedTo 状态刷新后丢失），未命中 = 已废弃/删除
  const [resolved, setResolved] = useState<Record<string, { existing: { id: string; path: string; module: string } | null } | null>>({});
  // 入库弹窗
  const [dialog, setDialog] = useState<{ file: string; open: boolean }>({ file: '', open: false });
  const [dlgModule, setDlgModule] = useState('');
  const [dlgCustom, setDlgCustom] = useState('');
  const [dlgReplace, setDlgReplace] = useState(false);
  const [dlgConflict, setDlgConflict] = useState<{ existing: { id: string; path: string; module: string } | null; count: number } | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [dlgError, setDlgError] = useState('');

  const refresh = useCallback(() => {
    draftsApi.list().then(r => {
      const m: Record<string, DraftItem> = {};
      for (const d of r.drafts || []) m[d.filename] = d;
      setMetaMap(m);
    }).catch(() => {});
    draftsApi.modules().then(r => setModules(r.modules || [])).catch(() => {});
    // K-xxx：依赖建议计数（按 consumer 场景 ID 聚合）
    draftsApi.suggestDeps().then(r => {
      const c: Record<string, number> = {};
      for (const s of r.suggestions || []) c[s.consumer] = (c[s.consumer] || 0) + 1;
      setSuggCount(c);
    }).catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // K-xxx：草稿去向判定——drafts 列表无此文件且本地无已入库状态时，查冲突预检区分「已入库/已删除」
  const draftsKey = draftFiles.join('|');
  useEffect(() => {
    let alive = true;
    (async () => {
      const next: Record<string, { existing: { id: string; path: string; module: string } | null } | null> = {};
      for (const f of draftFiles) {
        if (state[f]?.promotedTo || metaMap[f] || f in resolved) continue;
        try {
          const r = await draftsApi.conflict(f);
          if (alive) next[f] = { existing: r.existing };
        } catch { if (alive) next[f] = null; }
      }
      if (alive && Object.keys(next).length > 0) setResolved(prev => ({ ...prev, ...next }));
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftsKey, metaMap]);

  const setOne = (file: string, patch: Partial<DraftCardState>) =>
    setState(prev => ({ ...prev, [file]: { ...prev[file], ...patch } }));

  const handleValidate = async (file: string) => {
    setOne(file, { validating: true, validate: undefined });
    try {
      const r = await draftsApi.validate(file);
      setOne(file, { validate: r });
    } catch (e: any) {
      setOne(file, { validate: { verdict: 'ERROR', findings: [{ level: 'ERROR', rule: 'HTTP', message: e.message || '校验失败' }] } });
    } finally {
      setOne(file, { validating: false });
    }
  };

  const handleTrial = async (file: string) => {
    if (!window.confirm(`试跑将真实调用目标环境（按依赖闭包执行，会产生真实测试数据）。\n确认试跑 ${file}？`)) return;
    setOne(file, { running: true, trial: undefined });
    try {
      const r = await draftsApi.trialRun(file);
      setOne(file, { trial: r });
    } catch (e: any) {
      setOne(file, { trial: { ok: false, error: e.message || '试跑失败' } });
    } finally {
      setOne(file, { running: false });
    }
  };

  /** K-xxx：入库弹窗——预检 ID 冲突，冲突时自动选中既有模块并勾选覆盖 */
  const openPromote = async (file: string) => {
    setDialog({ file, open: true });
    setDlgModule('');
    setDlgCustom('');
    setDlgReplace(false);
    setDlgConflict(null);
    setDlgError('');
    try {
      const c = await draftsApi.conflict(file);
      setDlgConflict(c);
      if (c.existing) {
        setDlgModule(c.existing.module);   // 既有场景所在模块
        setDlgReplace(true);               // 覆盖更新语义
      }
    } catch { /* 预检失败不阻塞弹窗（入库时后端仍会拦） */ }
  };

  const handlePromote = async () => {
    const file = dialog.file;
    const module = dlgModule === '__new__' ? dlgCustom.trim() : dlgModule;
    if (!module) { setDlgError('请选择入库模块'); return; }
    setPromoting(true);
    setDlgError('');
    try {
      const r = await draftsApi.promote(file, module, dlgReplace);
      setOne(file, { promotedTo: r.target || module, scenarioId: r.scenario_id || '' });
      setDialog({ file: '', open: false });
      refresh();
    } catch (e: any) {
      setDlgError(e.message || '入库失败');
    } finally {
      setPromoting(false);
    }
  };

  const handleDiscard = async (file: string) => {
    if (!window.confirm(`确认废弃 ${file}？（移入 drafts/_trash/，可人工恢复）`)) return;
    try {
      await draftsApi.discard(file);
      setOne(file, { discarded: true });
      refresh();
    } catch (e: any) {
      onError(`废弃失败：${e.message || ''}`);
    }
  };

  const busyAll = promoting;

  return (
    <div className="px-2 py-2 space-y-2">
      <div className="px-1 text-xs font-medium text-gray-300">📝 草稿产物（Agent 会话内评审）</div>
      {draftFiles.length === 0 && (
        <div className="text-[11px] text-gray-600 text-center py-8 leading-relaxed">
          Agent 尚未写入草稿。<br />写入后自动出现在这里，<br />可直接查看 / 校验 / 试跑 / 入库
        </div>
      )}
      {draftFiles.map(file => {
        const meta = metaMap[file];
        const st = state[file] || {};
        if (st.discarded) return null;
        // 去向判定：① 本会话已入库 → ② 刷新后无本地状态，conflict 预检命中库内 = 已入库 → ③ 未命中 = 已删除
        const libHit = st.promotedTo
          ? { path: st.promotedTo, scenarioId: st.scenarioId || '' }
          : (resolved[file]?.existing
              ? { path: resolved[file]!.existing!.path, scenarioId: resolved[file]!.existing!.id }
              : null);
        const gone = !st.promotedTo && !meta && resolved[file] !== undefined && !resolved[file]?.existing;
        const checking = !st.promotedTo && !meta && resolved[file] === undefined;
        return (
          <div key={file} className="rounded-lg border border-border bg-surface-2/70 p-2">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] font-mono text-gray-200 truncate flex-1" title={file}>{file}</span>
              {meta?.stale && (
                <span className="text-[9px] text-yellow-400 flex-shrink-0" title="来源信息包存在已变更文件，草稿可能过时">⚠️</span>
              )}
              {meta && suggCount[meta.scenario_id] > 0 && !st.promotedTo && (
                <span className="text-[9px] text-info flex-shrink-0" title={`${suggCount[meta.scenario_id]} 条依赖建议——到草稿评审页可一键采纳`}>
                  💡{suggCount[meta.scenario_id]}
                </span>
              )}
            </div>
            <div className="text-[10px] truncate" title={meta?.title || libHit?.path || ''}>
              {libHit ? (
                <span className="text-green-400/90">✅ 已在场景库 · {libHit.scenarioId} · {libHit.path}</span>
              ) : gone ? (
                <span className="text-gray-600">草稿已不存在（已废弃或删除）</span>
              ) : checking ? (
                <span className="text-gray-600">检测草稿去向…</span>
              ) : meta
                ? `${meta.scenario_id || ''}${meta.title ? ` · ${meta.title}` : ''}`
                : '（草稿文件不存在或已删除）'}
            </div>

            {/* 校验结果 */}
            {st.validate && (
              <div className={`mt-1.5 text-[10px] rounded px-1.5 py-1 ${
                st.validate.verdict === 'PASS' ? 'bg-green-900/20 text-green-400' : 'bg-red-900/20 text-red-400'
              }`}>
                <div className="font-medium">
                  {st.validate.verdict}
                  {st.validate.summary && ` · error ${st.validate.summary.error ?? 0} / warn ${st.validate.summary.warn ?? 0}`}
                </div>
                {(st.validate.findings || []).slice(0, 4).map((f, i) => (
                  <div key={i} className={f.level === 'ERROR' ? 'text-red-400' : 'text-gray-500'}>
                    [{f.rule}] {f.message}
                  </div>
                ))}
              </div>
            )}
            {/* 试跑结果 */}
            {st.trial && (
              <div className={`mt-1.5 text-[10px] rounded px-1.5 py-1 ${
                st.trial.ok ? 'bg-green-900/20 text-green-400' : 'bg-red-900/20 text-red-400'
              }`}>
                {st.trial.ok
                  ? `✅ 试跑通过（${st.trial.verdict || ''}${st.trial.env ? ` @${st.trial.env}` : ''}）`
                  : `❌ 试跑失败：${st.trial.error || st.trial.reason || '未知错误'}`}
              </div>
            )}

            {/* 已入库（本会话或刷新后检出）：草稿已移入场景库，只留 DAG 跳转，不再提供草稿级操作 */}
            {libHit ? (
              <div className="flex items-center gap-1 mt-2">
                <button
                  onClick={() => navigate(`/dag?focus=${encodeURIComponent(libHit.scenarioId)}`)}
                  className="px-2 py-1 rounded bg-info/20 text-info text-[11px] hover:bg-info/30"
                  title="入库不是终点：到 DAG 编排里查看节点 / 连线 / 执行">
                  🕸 DAG 编排
                </button>
                <span className="ml-auto text-[9px] text-gray-600">
                  试跑/校验请到执行控制页选中该场景运行
                </span>
              </div>
            ) : gone ? (
              <div className="mt-2 text-[9px] text-gray-600">
                如需重新生成，请让 Agent 用 next_scenario_id 取新 ID
              </div>
            ) : (
              <div className="flex flex-wrap gap-1 mt-2">
                <button onClick={() => onViewFile(file, 'draft')} disabled={busyAll}
                  className="px-2 py-1 rounded bg-surface-3 text-gray-300 text-[11px] hover:bg-surface-1 disabled:opacity-40">查看</button>
                <button onClick={() => handleValidate(file)} disabled={busyAll}
                  className="px-2 py-1 rounded bg-surface-3 text-gray-300 text-[11px] hover:bg-surface-1 disabled:opacity-40">
                  {st.validating ? '校验中…' : '① 校验'}
                </button>
                <button onClick={() => handleTrial(file)} disabled={busyAll}
                  className="px-2 py-1 rounded bg-warn/20 text-warn text-[11px] hover:bg-warn/30 disabled:opacity-40">
                  {st.running ? '试跑中…' : '▶ 试跑'}
                </button>
                <button onClick={() => openPromote(file)} disabled={busyAll || !!st.promotedTo}
                  className="px-2 py-1 rounded bg-info text-white text-[11px] hover:bg-info/90 disabled:opacity-40">⬆ 入库</button>
                <button onClick={() => handleDiscard(file)} disabled={busyAll || !!st.promotedTo}
                  className="ml-auto px-2 py-1 rounded text-gray-500 text-[11px] hover:text-red-400 disabled:opacity-40">废弃</button>
              </div>
            )}
          </div>
        );
      })}

      {/* 入库弹窗（模块选择 + 覆盖勾选 + 冲突预检提示） */}
      {dialog.open && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center"
          onClick={() => !promoting && setDialog({ file: '', open: false })}>
          <div className="bg-surface-2 border border-border rounded-xl p-4 w-[440px] max-w-[92vw] shadow-2xl"
            onClick={e => e.stopPropagation()}>
            <div className="text-sm font-medium text-gray-200 mb-2">⬆ 入库评审 — <span className="font-mono">{dialog.file}</span></div>
            {dlgConflict?.existing && (
              <div className="mb-2 text-[11px] rounded bg-yellow-900/30 text-yellow-400 px-2 py-1.5 leading-relaxed">
                ⚠️ 场景 ID <span className="font-mono">{dlgConflict.existing.id}</span> 已存在于
                <span className="font-mono"> {dlgConflict.existing.path}</span>
                <div className="mt-0.5">已自动选中该模块并勾选「覆盖」（覆盖更新会备份原文件，失败自动回滚）；新增场景请改用 next_scenario_id 换新 ID。</div>
              </div>
            )}
            <div className="text-[11px] text-gray-500 mb-1">入库模块（scenarios/ 下）</div>
            <select value={dlgModule} onChange={e => { setDlgModule(e.target.value); setDlgError(''); }}
              className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-sm text-gray-300 mb-2">
              {modules.length === 0 && <option value="">（无已有模块）</option>}
              {modules.map(m => <option key={m} value={m}>{m}</option>)}
              <option value="__new__">＋ 新建模块…</option>
            </select>
            {dlgModule === '__new__' && (
              <input value={dlgCustom} onChange={e => setDlgCustom(e.target.value)}
                placeholder="新模块路径（如 system-settings/tag-library）"
                className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-sm text-gray-300 mb-2" />
            )}
            <label className="flex items-center gap-2 text-[12px] text-gray-400 mb-2 cursor-pointer select-none">
              <input type="checkbox" checked={dlgReplace} onChange={e => setDlgReplace(e.target.checked)} />
              覆盖同名场景（原文件备份 + 失败自动回滚）
            </label>
            {dlgError && <div className="mb-2 text-[11px] text-red-400">❌ {dlgError}</div>}
            <div className="flex justify-end gap-2">
              <button onClick={() => setDialog({ file: '', open: false })} disabled={promoting}
                className="px-3 py-1.5 rounded bg-surface-3 text-gray-300 text-sm disabled:opacity-40">取消</button>
              <button onClick={handlePromote} disabled={promoting}
                className="px-3 py-1.5 rounded bg-info text-white text-sm disabled:opacity-40">
                {promoting ? '入库中…（校验→基线→门禁）' : '确认入库'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
