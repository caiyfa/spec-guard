// 草稿区三道闸（D1）：评审 → 格式校验 → 发布门禁 → 入库 / 废弃
// K-046：评审期可编辑微调（表单/YAML 双模式）+ 依赖建议一键连线 + 未入库试跑，
//        入库成功自动跳转 DAG 编排聚焦——产出→编排→执行不再断线

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { draftsApi, referenceApi, scenariosApi } from '../api';
import type {
  DraftItem, ValidateReport, DepSuggestion, TrialRunResult,
  EmpRole, OracleRef, UpstreamVar, EnvVar,
} from '../api';
import ScenarioFormEditor from '../components/ScenarioFormEditor';

/** verdict 配色（PASS/FAIL/SKIP/BLOCKED） */
const VERDICT_STYLE: Record<string, string> = {
  PASS: 'text-pass', FAIL: 'text-fail', SKIP: 'text-skip', BLOCKED: 'text-blocked',
};

export default function Drafts() {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState<DraftItem[]>([]);
  const [modules, setModules] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [content, setContent] = useState<string>('');
  const [report, setReport] = useState<ValidateReport | null>(null);
  const [targetModule, setTargetModule] = useState<string>('');
  const [customModule, setCustomModule] = useState('');  // K-017: 「新建模块…」手动输入
  // A+B: 当前选中草稿的依赖关系（从 read_draft 响应解析）
  const [dependsOn, setDependsOn] = useState<string[]>([]);
  // K-xxx：覆盖入库（replace）+ 入库前 ID 冲突预检（选错模块/更新已有场景时提前提示）
  const [replace, setReplace] = useState(false);
  const [conflict, setConflict] = useState<{ existing: { id: string; path: string; module: string } | null; count: number } | null>(null);
  const [busy, setBusy] = useState<'validate' | 'promote' | 'discard' | 'save' | 'trial' | 'dep' | 'review' | ''>('');
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [error, setError] = useState('');
  // K-046：依赖建议 + 试跑结果
  const [allSuggestions, setAllSuggestions] = useState<DepSuggestion[]>([]);
  const [unresolved, setUnresolved] = useState<Record<string, string[]>>({});
  const [trialResult, setTrialResult] = useState<TrialRunResult | null>(null);
  // K-046：编辑器参考数据（与 DagEditor 同一来源）
  const [empRoles, setEmpRoles] = useState<EmpRole[]>([]);
  const [oracles, setOracles] = useState<OracleRef[]>([]);
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [upstreamVars, setUpstreamVars] = useState<UpstreamVar[]>([]);
  const [allScenarios, setAllScenarios] = useState<{ id: string; title: string }[]>([]);

  const refresh = useCallback(async () => {
    try {
      const [d, m] = await Promise.all([draftsApi.list(), draftsApi.modules()]);
      setDrafts(d.drafts);
      setModules(m.modules);
      if (!targetModule && m.modules.length > 0) setTargetModule(m.modules[0]);
    } catch (e: any) {
      setError(e.message || '加载失败');
    }
  }, [targetModule]);

  const refreshSuggestions = useCallback(async () => {
    try {
      const r = await draftsApi.suggestDeps();
      setAllSuggestions(r.suggestions || []);
      setUnresolved(r.unresolved || {});
    } catch { /* 建议加载失败不阻断主流程 */ }
  }, []);

  useEffect(() => { refresh(); refreshSuggestions(); }, [refresh, refreshSuggestions]);
  useEffect(() => {
    referenceApi.empRoles().then(setEmpRoles).catch(() => {});
    referenceApi.oracles().then(setOracles).catch(() => {});
    referenceApi.envVars().then(setEnvVars).catch(() => {});
    scenariosApi.list().then(list => setAllScenarios(list.map(s => ({ id: s.id, title: s.title })))).catch(() => {});
  }, []);

  /** 当前选中草稿的场景 ID（列表项已解析出） */
  const selectedDraft = useMemo(() => drafts.find(d => d.filename === selected), [drafts, selected]);
  const selectedScenarioId = selectedDraft?.scenario_id || '';

  /** 当前草稿的依赖建议（consumer = 场景 ID） */
  const suggestions = useMemo(
    () => allSuggestions.filter(s => s.consumer === selectedScenarioId),
    [allSuggestions, selectedScenarioId],
  );
  const selectedUnresolved = unresolved[selectedScenarioId] || [];

  // 上游变量参考（草稿的 depends_on 可能刚加，id 未必在库内——失败静默置空）
  useEffect(() => {
    if (!selectedScenarioId) { setUpstreamVars([]); return; }
    referenceApi.upstreamVars(selectedScenarioId).then(setUpstreamVars).catch(() => setUpstreamVars([]));
  }, [selectedScenarioId, content]);

  const handleSelect = async (filename: string) => {
    setSelected(filename);
    setReport(null);
    setMessage(null);
    setError('');
    setTrialResult(null);
    setReplace(false);
    setConflict(null);
    // K-xxx：入库前 ID 冲突预检——草稿 ID 已存在于场景库时自动选中既有模块并勾选覆盖
    draftsApi.conflict(filename).then(c => {
      setConflict(c);
      if (c.existing) {
        setTargetModule(c.existing.module);
        setReplace(true);
      }
    }).catch(() => {});
    try {
      const r = await draftsApi.read(filename);
      setContent(r.content);
      setDependsOn(r.depends_on || []);
    } catch (e: any) {
      setError(e.message || '读取草稿失败');
      setContent('');
    }
  };

  const handleValidate = async () => {
    if (!selected) return;
    setBusy('validate');
    setMessage(null);
    try {
      const r = await draftsApi.validate(selected);
      setReport(r);
    } catch (e: any) {
      setError(e.message || '校验失败');
    } finally {
      setBusy('');
    }
  };

  /** K-046：编辑器保存（写回 drafts/ 沙箱，写前后端自动 .bak 备份） */
  const handleSave = async (yamlStr: string) => {
    if (!selected) return;
    setBusy('save');
    try {
      await draftsApi.update(selected, yamlStr);
      const r = await draftsApi.read(selected);
      setContent(r.content);
      setReport(null);          // 内容已变，旧校验报告失效
      await refreshSuggestions();  // 依赖建议随之重算
    } finally {
      setBusy('');
    }
  };

  /** K-046：采纳依赖建议（文本外科手术写入草稿 depends_on） */
  const handleAcceptDep = async (sug: DepSuggestion) => {
    if (!selected) return;
    setBusy('dep');
    setMessage(null);
    try {
      await draftsApi.addDep(selected, sug.dep_id);
      const r = await draftsApi.read(selected);
      setContent(r.content);
      setMessage({ ok: true, text: `✅ 已连线：${selectedScenarioId} → 依赖 ${sug.dep_id}` });
      await refreshSuggestions();
    } catch (e: any) {
      setMessage({ ok: false, text: `❌ 连线失败：${e.message}` });
    } finally {
      setBusy('');
    }
  };

  /** K-046：草稿试跑（未入库先验证，与 Agent run_scenario 同一语义） */
  const handleTrialRun = async () => {
    if (!selected) return;
    if (!window.confirm(`试跑将真实调用目标环境（按依赖闭包执行，会产生真实测试数据）。\n确认试跑 ${selectedScenarioId || selected}？`)) return;
    setBusy('trial');
    setMessage(null);
    setTrialResult(null);
    try {
      const r = await draftsApi.trialRun(selected);
      setTrialResult(r);
    } catch (e: any) {
      setTrialResult({ ok: false, error: e.message || '试跑失败' });
    } finally {
      setBusy('');
    }
  };

  const handlePromote = async () => {
    if (!selected) return;
    // K-017：模块目录后端自动创建；「新建模块…」选项时使用手动输入的路径
    const effectiveModule = targetModule === '__new__' ? customModule.trim() : targetModule;
    if (!effectiveModule) {
      setMessage({ ok: false, text: '❌ 请选择入库模块，或选择「新建模块…」输入新模块路径' });
      return;
    }
    if (!window.confirm(`确认将 ${selected} 入库到 scenarios/${effectiveModule}/？\n将依次执行：格式校验 → 更新契约基线 → 发布门禁（失败自动回滚）${replace ? '\n（已勾选覆盖同名场景，原文件自动备份）' : ''}`)) return;
    setBusy('promote');
    setMessage(null);
    try {
      const r = await draftsApi.promote(selected, effectiveModule, replace);
      const sid = r.scenario_id || selectedScenarioId;
      setMessage({ ok: true, text: `✅ 入库成功：${r.target}${r.gate?.skipped ? '（门禁已跳过）' : '（发布门禁 PASS）'}，即将跳转 DAG 编排…` });
      setSelected('');
      setContent('');
      setReport(null);
      await refresh();
      // K-046：入库不是终点——跳 DAG 聚焦新节点继续编排
      setTimeout(() => navigate(`/dag?focus=${encodeURIComponent(sid)}`), 800);
    } catch (e: any) {
      setMessage({ ok: false, text: `❌ 入库失败：${e.message}` });
    } finally {
      setBusy('');
    }
  };

  const handleDiscard = async () => {
    if (!selected) return;
    if (!window.confirm(`确认废弃 ${selected}？（移入 drafts/_trash/，可人工恢复）`)) return;
    setBusy('discard');
    setMessage(null);
    try {
      await draftsApi.discard(selected);
      setMessage({ ok: true, text: `已废弃：${selected}` });
      setSelected('');
      setContent('');
      setReport(null);
      await refresh();
    } catch (e: any) {
      setMessage({ ok: false, text: `❌ 废弃失败：${e.message}` });
    } finally {
      setBusy('');
    }
  };

  // T-061：第①闸人工评审（人拍板，留痕 reviewer+ts）
  const handleReview = async (decision: 'approved' | 'rejected') => {
    if (!selected) return;
    if (decision === 'rejected' && !window.confirm(`确认驳回 ${selected}？（第②闸校验通过前评审通过会被拒绝）`)) return;
    setBusy('review');
    setMessage(null);
    try {
      const r = await draftsApi.review(selected, decision);
      setMessage({
        ok: true,
        text: decision === 'approved'
          ? `✅ 第①闸评审通过（${r.gates.gate1_reviewer || ''}）——三闸齐备后可入库`
          : `已驳回：${selected}`,
      });
      await refresh();
    } catch (e: any) {
      setMessage({ ok: false, text: `❌ 评审失败：${e.message}` });
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="flex gap-4 h-full">
      {/* 左：草稿列表 */}
      <div className="w-80 flex-shrink-0 flex flex-col">
        <div className="mb-3">
          <h2 className="text-lg font-bold text-gray-200">📝 草稿评审</h2>
          <p className="text-xs text-gray-500 mt-1">
            Agent 产物三道闸：人工评审（可微调）→ 格式校验 → 发布门禁，缺一不入库。
          </p>
        </div>
        <div className="flex-1 overflow-y-auto space-y-1.5">
          {drafts.length === 0 && (
            <div className="text-center text-gray-600 text-sm py-10">草稿区为空</div>
          )}
          {drafts.map(d => {
            const sugCount = allSuggestions.filter(s => s.consumer === d.scenario_id).length;
            return (
              <button
                key={d.filename}
                onClick={() => handleSelect(d.filename)}
                className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
                  selected === d.filename
                    ? 'border-info bg-info/10'
                    : 'border-border bg-surface-2 hover:bg-surface-3'
                }`}
              >
                <div className="text-sm text-gray-200 font-mono">
                  {d.scenario_id || d.filename}
                  {d.stale && (
                    <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-yellow-900/40 text-yellow-400 font-normal"
                      title={`来源信息包（${d.source_meta}）存在已变更/已删除文件，草稿内容可能过时`}>
                      ⚠️ 信息包已变更
                    </span>
                  )}
                  {sugCount > 0 && (
                    <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-info/20 text-info font-normal"
                      title="确定性引擎检测到可连线的依赖建议">
                      💡 {sugCount} 条建议
                    </span>
                  )}
                </div>
                <div className="text-xs text-gray-500 truncate">{d.title || d.filename}</div>
                <div className="text-[10px] text-gray-600 mt-0.5">
                  {d.modified}{d.author ? ` · ${d.author}` : ''}
                </div>
                {/* T-061：三闸状态徽章 */}
                {d.gates && (
                  <div className="flex items-center gap-1 mt-1 flex-wrap">
                    <span className={`text-[9px] px-1 py-0.5 rounded ${d.gates.g1 === 'approved' ? 'bg-green-900/40 text-green-400' : d.gates.g1 === 'rejected' ? 'bg-red-900/40 text-red-400' : 'bg-yellow-900/40 text-yellow-400'}`}>
                      ① {d.gates.g1 === 'approved' ? '已评审' : d.gates.g1 === 'rejected' ? '已驳回' : '待评审'}
                    </span>
                    <span className={`text-[9px] px-1 py-0.5 rounded ${d.gates.g2 === 'pass' ? 'bg-green-900/40 text-green-400' : d.gates.g2 === 'fail' ? 'bg-red-900/40 text-red-400' : 'bg-surface-3 text-gray-500'}`}>
                      ② {d.gates.g2 === 'pass' ? '校验✓' : d.gates.g2 === 'fail' ? '校验✗' : '待校验'}
                    </span>
                    <span className={`text-[9px] px-1 py-0.5 rounded ${d.gates.g3 === 'pass' ? 'bg-green-900/40 text-green-400' : d.gates.g3 === 'fail' ? 'bg-red-900/40 text-red-400' : 'bg-surface-3 text-gray-500'}`}>
                      ③ {d.gates.g3 === 'pass' ? '门禁✓' : d.gates.g3 === 'fail' ? '门禁✗' : '门禁⏸'}
                    </span>
                    {d.source_delta && (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-info/15 text-info/90" title="血缘挂链：来源 delta">
                        ← {d.source_delta}
                      </span>
                    )}
                  </div>
                )}
                {/* A+B：文件依赖展示 */}
                {d.source_files && d.source_files.length > 0 && (
                  <div className="mt-1">
                    <details className="text-[10px]">
                      <summary className="cursor-pointer text-gray-500 hover:text-gray-300">
                        📄 {d.source_files.length} 个文件依赖
                      </summary>
                      <div className="mt-1 pl-3 space-y-0.5">
                        {d.source_files.map((f, i) => (
                          <div key={i} className="text-gray-600 truncate" title={f}>{f}</div>
                        ))}
                      </div>
                    </details>
                  </div>
                )}
                {/* K-026：信息包关联可见化——此前仅 stale 时 tooltip 提及，用户看不到草稿来自哪个信息包 */}
                {d.source_meta && (
                  <div className="text-[10px] mt-0.5">
                    <span className="px-1 py-0.5 rounded bg-info/15 text-info/90"
                      title={`本草稿由信息包 ${d.source_meta} 派生（Agent 对话生成）`}>
                      📦 {d.source_meta}
                    </span>
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* 右：内容与操作 */}
      <div className="flex-1 flex flex-col min-w-0">
        {message && (
          <div className={`mb-3 px-3 py-2 rounded-lg text-sm ${
            message.ok ? 'bg-green-900/30 text-green-400 border border-green-700/50'
                       : 'bg-red-900/30 text-red-400 border border-red-700/50'
          }`}>{message.text}</div>
        )}
        {error && (
          <div className="mb-3 px-3 py-2 rounded-lg text-sm bg-red-900/30 text-red-400 border border-red-700/50">
            ❌ {error}
          </div>
        )}

        {!selected ? (
          <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">
            选择左侧草稿开始评审
          </div>
        ) : (
          <>
            {/* 操作栏 */}
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              {/* T-061：三闸状态卡（write 自动跑② → 人评审① → promote 跑③） */}
              <div className="flex items-center gap-1 px-2 py-1 rounded bg-surface-2 border border-border text-[10px]">
                <span className={`px-1 py-0.5 rounded ${selectedDraft?.gates?.g1 === 'approved' ? 'bg-green-900/40 text-green-400' : selectedDraft?.gates?.g1 === 'rejected' ? 'bg-red-900/40 text-red-400' : 'bg-yellow-900/40 text-yellow-400'}`}>
                  ① {selectedDraft?.gates?.g1 === 'approved' ? '已评审' : selectedDraft?.gates?.g1 === 'rejected' ? '已驳回' : '待评审'}
                </span>
                <span className={`px-1 py-0.5 rounded ${selectedDraft?.gates?.g2 === 'pass' ? 'bg-green-900/40 text-green-400' : selectedDraft?.gates?.g2 === 'fail' ? 'bg-red-900/40 text-red-400' : 'bg-surface-3 text-gray-500'}`}>
                  ② {selectedDraft?.gates?.g2 === 'pass' ? '校验✓' : selectedDraft?.gates?.g2 === 'fail' ? '校验✗' : '待校验'}
                </span>
                <span className={`px-1 py-0.5 rounded ${selectedDraft?.gates?.g3 === 'pass' ? 'bg-green-900/40 text-green-400' : selectedDraft?.gates?.g3 === 'fail' ? 'bg-red-900/40 text-red-400' : 'bg-surface-3 text-gray-500'}`}>
                  ③ {selectedDraft?.gates?.g3 === 'pass' ? '门禁✓' : selectedDraft?.gates?.g3 === 'fail' ? '门禁✗' : '门禁⏸'}
                </span>
              </div>
              <button
                onClick={handleValidate}
                disabled={busy !== ''}
                className="px-3 py-1.5 bg-surface-3 text-gray-200 rounded text-sm hover:bg-surface-2 disabled:opacity-40"
              >
                {busy === 'validate' ? '校验中…' : '② 格式校验'}
              </button>
              {/* T-061：第①闸人工评审（人拍板） */}
              <button
                onClick={() => handleReview('approved')}
                disabled={busy !== ''}
                title="第①闸人工评审通过（gate2 未过时会被拒绝）；三闸全过才可入库"
                className="px-3 py-1.5 bg-green-900/40 text-green-400 rounded text-sm hover:bg-green-900/60 disabled:opacity-40"
              >
                {busy === 'review' ? '评审中…' : '① 评审通过'}
              </button>
              <button
                onClick={() => handleReview('rejected')}
                disabled={busy !== ''}
                className="px-3 py-1.5 bg-red-900/30 text-red-400 rounded text-sm hover:bg-red-900/50 disabled:opacity-40"
              >
                驳回
              </button>
              <button
                onClick={handleTrialRun}
                disabled={busy !== ''}
                title="未入库先试跑：按依赖闭包真实执行（与 Agent run_scenario 同一语义）"
                className="px-3 py-1.5 bg-warn/20 text-warn rounded text-sm hover:bg-warn/30 disabled:opacity-40"
              >
                {busy === 'trial' ? '试跑中…（联网执行，请稍候）' : '▶ 试跑'}
              </button>
              <select
                value={targetModule}
                onChange={e => setTargetModule(e.target.value)}
                className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300"
              >
                {modules.length === 0 && <option value="">（无已有模块）</option>}
                {modules.map(m => <option key={m} value={m}>{m}</option>)}
                <option value="__new__">＋ 新建模块…</option>
              </select>
              {targetModule === '__new__' && (
                <input
                  value={customModule}
                  onChange={e => setCustomModule(e.target.value)}
                  placeholder="新模块路径（如 system-settings/tag-library）"
                  className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300 w-56"
                />
              )}
              <label className="flex items-center gap-1.5 text-sm text-gray-400 cursor-pointer select-none"
                title="覆盖同名场景：原文件自动备份，任一步失败自动回滚（T-313）">
                <input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)} />
                覆盖同名场景
              </label>
              {/* K-xxx：入库前冲突预检——草稿 ID 已存在于场景库时的可执行提示 */}
              {conflict?.existing && (
                <div className="w-full text-[11px] rounded bg-yellow-900/30 text-yellow-400 px-2 py-1.5 leading-relaxed">
                  ⚠️ 场景 ID <span className="font-mono">{conflict.existing.id}</span> 已存在于
                  <span className="font-mono"> {conflict.existing.path}</span>
                  {conflict.existing.module === (targetModule === '__new__' ? customModule.trim() : targetModule)
                    ? ' ——已自动选中该模块并勾选「覆盖」，可直接入库更新'
                    : ' ——不在当前所选模块，请切换模块（更新）或改用 next_scenario_id 换新 ID（新增）'}
                </div>
              )}
              <button
                onClick={handlePromote}
                disabled={busy !== '' || (report !== null && report.verdict !== 'PASS')}
                title={report !== null && report.verdict !== 'PASS' ? '格式校验未通过，禁止入库' : ''}
                className="px-3 py-1.5 bg-info text-white rounded text-sm hover:bg-info/90 disabled:opacity-40"
              >
                {busy === 'promote' ? '入库中…' : '③ 三闸全过 · 入库'}
              </button>
              <button
                onClick={handleDiscard}
                disabled={busy !== ''}
                className="px-3 py-1.5 bg-red-900/40 text-red-400 rounded text-sm hover:bg-red-900/60 disabled:opacity-40"
              >
                废弃
              </button>
            </div>

            {/* A+B：依赖关系展示 */}
            {dependsOn.length > 0 && (
              <div className="mb-3 px-3 py-2 rounded-lg border border-yellow-700/30 bg-yellow-900/10 text-sm">
                <div className="text-yellow-400 text-xs font-medium mb-1.5">
                  🕸 依赖关系（已声明 depends_on）
                </div>
                <ul className="space-y-1">
                  {dependsOn.map((dep, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs">
                      <span className="px-1.5 py-0.5 rounded bg-info/20 text-info font-mono text-[10px]">
                        {dep}
                      </span>
                      <span className="text-gray-500">上游依赖</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* K-046：依赖建议面板 */}
            {(suggestions.length > 0 || selectedUnresolved.length > 0) && (
              <div className="mb-3 px-3 py-2 rounded-lg border border-info/40 bg-info/5 text-sm">
                <div className="text-info text-xs font-medium mb-1.5">
                  💡 依赖建议（确定性引擎扫描插值得出，采纳即写入 depends_on）
                </div>
                <ul className="space-y-1">
                  {suggestions.map((s, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs">
                      <span className={`px-1 py-0.5 rounded ${
                        s.confidence === 'high' ? 'bg-pass/20 text-pass' : 'bg-warn/20 text-warn'
                      }`}>{s.confidence === 'high' ? '高置信' : '中置信'}</span>
                      <span className="font-mono text-gray-200">{s.dep_id}</span>
                      <span className="text-gray-500 truncate flex-1" title={s.reason}>
                        {s.dep_title || s.reason}
                      </span>
                      <button
                        onClick={() => handleAcceptDep(s)}
                        disabled={busy !== ''}
                        title={s.reason}
                        className="px-2 py-0.5 bg-info/20 text-info rounded hover:bg-info/30 disabled:opacity-40"
                      >
                        采纳
                      </button>
                    </li>
                  ))}
                </ul>
                {selectedUnresolved.length > 0 && (
                  <div className="mt-1.5 text-[11px] text-gray-500"
                    title="这些插值根没有匹配到任何生产者，可能是运行时内置变量或悬空引用">
                    ⚠️ 未解析引用：{selectedUnresolved.join('、')}
                  </div>
                )}
              </div>
            )}

            {/* K-046：试跑结果 */}
            {trialResult && (
              <div className={`mb-3 px-3 py-2 rounded-lg border text-sm ${
                trialResult.ok ? 'border-green-700/50 bg-green-900/20' : 'border-red-700/50 bg-red-900/20'
              }`}>
                <div className={trialResult.ok ? 'text-green-400' : 'text-red-400'}>
                  {trialResult.ok ? `✓ 试跑通过（${trialResult.env || 'sit'}）`
                    : `✗ 试跑 ${trialResult.verdict || '失败'}${trialResult.error ? `：${trialResult.error}` : ''}`}
                </div>
                {trialResult.records && trialResult.records.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5">
                    {trialResult.records.map((r, i) => (
                      <li key={i} className="text-xs">
                        <span className={`font-medium ${VERDICT_STYLE[r.verdict] || 'text-gray-400'}`}>
                          {r.verdict}
                        </span>
                        <span className="ml-2 font-mono text-gray-300">{r.scenario_id}</span>
                        {r.error && <span className="ml-2 text-red-400/80">{r.error}</span>}
                        {r.reason && <span className="ml-2 text-gray-500">{r.reason}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {trialResult.report_dir && (
                  <div className="mt-1 text-[10px] text-gray-600">报告：{trialResult.report_dir}</div>
                )}
              </div>
            )}

            {/* 校验报告 */}
            {report && (
              <div className={`mb-3 px-3 py-2 rounded-lg border text-sm ${
                report.verdict === 'PASS' ? 'border-green-700/50 bg-green-900/20' : 'border-red-700/50 bg-red-900/20'
              }`}>
                <div className={report.verdict === 'PASS' ? 'text-green-400' : 'text-red-400'}>
                  {report.verdict === 'PASS' ? '✓ 格式校验通过' : '✗ 格式校验未通过'}
                  {report.summary && `（ERROR ${report.summary.error} / WARN ${report.summary.warn}）`}
                </div>
                {report.findings.length > 0 && (
                  <ul className="mt-1.5 space-y-1">
                    {report.findings.map((f, i) => (
                      <li key={i} className={`text-xs ${f.level === 'ERROR' ? 'text-red-400' : 'text-yellow-500'}`}>
                        [{f.level}/{f.rule}] {f.message}{f.hint ? `（${f.hint}）` : ''}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* K-046：可编辑微调（表单/YAML 双模式，与 DAG 抽屉编辑器同一组件） */}
            <div className="flex-1 min-h-0 border border-border rounded-lg overflow-hidden">
              {content ? (
                <ScenarioFormEditor
                  scenarioId={selectedScenarioId || selected}
                  yamlContent={content}
                  empRoles={empRoles}
                  oracles={oracles}
                  upstreamVars={upstreamVars}
                  envVars={envVars}
                  allScenarios={allScenarios}
                  onSave={handleSave}
                />
              ) : (
                <div className="h-full flex items-center justify-center text-gray-600 text-sm">加载中…</div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
