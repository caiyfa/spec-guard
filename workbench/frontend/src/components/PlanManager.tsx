/**
 * PlanManager — 测试计划管理（K-011：从原 Plans 页迁入测试执行页）
 *
 * 计划列表 + Delta 导入（预览/确认两步）+ 编辑抽屉（名称/env/描述/断点/场景勾选/执行历史）。
 * 选中态与父页面（RunControl 顶部计划下拉）通过 props 双向同步。
 */

import { useEffect, useState } from 'react';
import { plansApi, scenariosApi, specApi } from '../api';
import type { TestPlan, Scenario, RunSummary, DeltaInfo, ImportPreview } from '../api';

interface Props {
  selectedPlan: string;
  onSelect: (planId: string) => void;
  onPlansChange: (plans: TestPlan[]) => void;
}

export default function PlanManager({ selectedPlan, onSelect, onPlansChange }: Props) {
  const [plans, setPlans] = useState<TestPlan[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [deltas, setDeltas] = useState<DeltaInfo[]>([]);
  const [msg, setMsg] = useState('');
  // 编辑抽屉
  const [editing, setEditing] = useState<string | null>(null);
  const [editData, setEditData] = useState<Partial<TestPlan>>({});
  const [history, setHistory] = useState<RunSummary[]>([]);
  // 导入流程
  const [showImport, setShowImport] = useState(false);
  const [importDelta, setImportDelta] = useState('');
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState(false);

  const reload = () => {
    plansApi.list().then((p) => { setPlans(p); onPlansChange(p); });
    scenariosApi.list().then(setScenarios);
    specApi.deltas().then((r) => {
      setDeltas(r.deltas);
      if (r.current) setImportDelta(r.current);
    });
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(reload, []);

  // 打开编辑抽屉 → 加载详情 + 历史
  useEffect(() => {
    if (!editing) { setHistory([]); return; }
    plansApi.get(editing).then(setEditData).catch(() => {});
    plansApi.history(editing).then(setHistory).catch(() => setHistory([]));
  }, [editing]);

  // 打开导入对话框 → 加载预览
  const openImport = async () => {
    if (!importDelta) return;
    setShowImport(true);
    setPreview(null);
    setSelectedFiles(new Set());
    try {
      const p = await plansApi.importPreview(importDelta);
      setPreview(p);
      // 默认全选合格文件
      setSelectedFiles(new Set(p.files.filter((f) => f.valid).map((f) => f.path)));
    } catch { setPreview(null); }
  };

  // 确认导入
  const confirmImport = async () => {
    if (!importDelta) return;
    setImporting(true);
    setMsg('');
    try {
      const r = await plansApi.importConfirm(importDelta, [...selectedFiles]);
      setMsg(`✓ 导入 ${r.imported_count} 个文件，匹配 ${r.matched_scenarios} 个场景`);
      setShowImport(false);
      onSelect(importDelta);
      reload();
    } catch (e: unknown) {
      setMsg(`✗ ${e instanceof Error ? e.message : '导入失败'}`);
    } finally { setImporting(false); }
  };

  // 列表项直接执行（SSE 事件流会广播到 RunControl 的监控面板）
  const run = async (planId: string) => {
    try {
      const r = await plansApi.run(planId);
      setMsg(`✓ 已触发 ${r.scenario_count} 个场景`);
    } catch (e: unknown) {
      setMsg(`✗ ${e instanceof Error ? e.message : '触发失败'}`);
    }
  };

  const remove = async (planId: string) => {
    if (!confirm(`确定删除计划 ${planId}？`)) return;
    await plansApi.delete(planId);
    if (editing === planId) setEditing(null);
    if (selectedPlan === planId) onSelect('');
    reload();
  };

  const save = async () => {
    if (!editing) return;
    setMsg('');
    try {
      await plansApi.save(editing, editData);
      setMsg('✓ 已保存');
      reload();
    } catch (e: unknown) {
      setMsg(`✗ ${e instanceof Error ? e.message : '保存失败'}`);
    }
  };

  const toggleScenario = (sid: string) => {
    const current = (editData.filter?.scenarios || []) as string[];
    const next = current.includes(sid) ? current.filter((s) => s !== sid) : [...current, sid];
    setEditData({ ...editData, filter: { ...editData.filter, scenarios: next } });
  };

  const toggleFile = (path: string) => {
    const next = new Set(selectedFiles);
    if (next.has(path)) next.delete(path); else next.add(path);
    setSelectedFiles(next);
  };

  return (
    <div className="w-60 flex-shrink-0 flex flex-col border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 border-b border-border bg-surface-2">
        <span className="text-xs font-medium">测试计划（{plans.length}）</span>
      </div>
      {/* 从 Delta 导入 */}
      <div className="px-2 py-2 border-b border-border bg-surface-2/50">
        <div className="flex gap-1.5">
          <select value={importDelta} onChange={(e) => setImportDelta(e.target.value)}
            className="flex-1 min-w-0 bg-surface-3 border border-border rounded px-1.5 py-1 text-[10px]">
            {deltas.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
          </select>
          <button onClick={openImport}
            className="px-2 py-1 rounded text-[10px] bg-info/20 text-info hover:bg-info/30">
            📥 导入
          </button>
        </div>
      </div>
      {msg && (
        <div className={`px-2 py-1 text-[10px] border-b border-border/30 ${msg.startsWith('✓') ? 'text-pass' : 'text-fail'}`}>
          {msg}
        </div>
      )}
      {/* 计划列表 */}
      <div className="flex-1 overflow-y-auto">
        {plans.length === 0 && (
          <div className="text-center text-gray-600 text-xs py-6">暂无计划<br />从上方 Delta 导入生成</div>
        )}
        {plans.map((p) => (
          <div key={p.id} onClick={() => onSelect(p.id)}
            className={`px-2.5 py-2 border-b border-border/30 cursor-pointer transition-colors ${
              selectedPlan === p.id ? 'bg-info/10 border-l-2 border-l-info' : 'hover:bg-surface-3'
            }`}>
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-gray-200 truncate">{p.name}</span>
              <span className="text-[10px] text-gray-500 flex-shrink-0 ml-1">{p.scenario_count} 场景</span>
            </div>
            <div className="flex items-center gap-1.5 mt-1 flex-wrap">
              <span className="text-[9px] px-1 py-0.5 rounded bg-surface-3 text-gray-500">{p.env}</span>
              {p.source_delta && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-info/10 text-info/60">📄 {p.source_delta}</span>
              )}
              {(p.breakpoints || []).length > 0 && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-fail/10 text-fail/70"
                  title={`断点：${(p.breakpoints || []).join('、')}`}>
                  🔴 {(p.breakpoints || []).length}
                </span>
              )}
              <span className="flex-1" />
              <button onClick={(e) => { e.stopPropagation(); run(p.id); }}
                className="text-[9px] text-pass hover:underline">▶ 执行</button>
              <button onClick={(e) => { e.stopPropagation(); setEditing(p.id); }}
                className="text-[9px] text-gray-500 hover:text-info">✏️ 编辑</button>
              <button onClick={(e) => { e.stopPropagation(); remove(p.id); }}
                className="text-[9px] text-gray-600 hover:text-fail">删除</button>
            </div>
          </div>
        ))}
      </div>

      {/* 导入预览对话框 */}
      {showImport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowImport(false)}>
          <div className="w-[700px] max-h-[80vh] bg-surface border border-border rounded-xl overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}>
            <div className="px-4 py-3 border-b border-border flex items-center justify-between bg-surface-2">
              <span className="text-sm font-medium">📥 从 Delta 导入：{importDelta}</span>
              <button onClick={() => setShowImport(false)} className="text-gray-500 hover:text-gray-300">✕</button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {!preview ? (
                <div className="text-center text-gray-500 py-8">加载预览中…</div>
              ) : (
                <>
                  {/* 概要 */}
                  <div className="mb-4 p-3 bg-surface-2 rounded-lg">
                    <div className="text-sm font-medium text-gray-200">{preview.proposal.name}</div>
                    <div className="text-[11px] text-gray-500 mt-1">{preview.proposal.description}</div>
                    <div className="flex gap-4 mt-2 text-[11px] text-gray-400">
                      <span>📄 {preview.summary.total_files} 文件</span>
                      <span>🧪 unit {preview.summary.unit_count}</span>
                      <span>🔗 scenario {preview.summary.scenario_count}</span>
                      <span>✅ valid {preview.summary.valid_count}</span>
                      {preview.summary.error_count > 0 && <span className="text-fail">❌ error {preview.summary.error_count}</span>}
                    </div>
                  </div>

                  {/* 文件清单 */}
                  <div className="text-[11px] text-gray-400 font-medium mb-2">选择要导入的文件（{selectedFiles.size}/{preview.files.length}）</div>
                  <div className="space-y-1 max-h-64 overflow-y-auto">
                    {preview.files.map((f) => (
                      <label key={f.path}
                        className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors ${
                          selectedFiles.has(f.path)
                            ? 'border-info/40 bg-info/5'
                            : f.valid ? 'border-border/30 hover:bg-surface-3' : 'border-fail/30 bg-fail/5 opacity-60'
                        }`}>
                        <input type="checkbox" checked={selectedFiles.has(f.path)}
                          onChange={() => toggleFile(f.path)} disabled={!f.valid} />
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                          f.test_type === 'unit' ? 'bg-pass/10 text-pass' : 'bg-info/10 text-info'
                        }`}>{f.test_type}</span>
                        <span className="text-xs text-gray-300 flex-1 truncate">{f.path}</span>
                        <span className="text-[10px] text-gray-500">{f.frs.length} FR</span>
                        {!f.valid && <span className="text-[10px] text-fail">{f.errors.join('; ')}</span>}
                      </label>
                    ))}
                  </div>

                  {/* 匹配场景 */}
                  {preview.matched_scenarios.length > 0 && (
                    <div className="mt-4">
                      <div className="text-[11px] text-gray-400 font-medium mb-1">
                        匹配已有场景（{preview.matched_scenarios.length}）
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {preview.matched_scenarios.map((s) => (
                          <span key={s.id} className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-gray-400 font-mono">
                            {s.id}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {preview.unmatched_frs.length > 0 && (
                    <div className="mt-3">
                      <div className="text-[11px] text-skip font-medium mb-1">
                        ⚠️ 待生成测试的 FR（{preview.unmatched_frs.length}）
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {preview.unmatched_frs.map((fr) => (
                          <span key={fr} className="text-[10px] px-1.5 py-0.5 rounded bg-skip/10 text-skip font-mono">{fr}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
            <div className="px-4 py-3 border-t border-border flex justify-end gap-2 bg-surface-2">
              <button onClick={() => setShowImport(false)}
                className="px-3 py-1.5 rounded text-xs text-gray-400 hover:text-gray-200">取消</button>
              <button onClick={confirmImport} disabled={importing || selectedFiles.size === 0}
                className="px-4 py-1.5 rounded text-xs bg-info/20 text-info hover:bg-info/30 disabled:opacity-40">
                {importing ? '导入中…' : `确认导入（${selectedFiles.size} 个文件）`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 编辑抽屉（仿 DagEditor ScenarioFormEditor 右侧抽屉模式） */}
      {editing && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={() => setEditing(null)}>
          <div className="w-[480px] max-w-full h-full bg-surface border-l border-border flex flex-col"
            onClick={(e) => e.stopPropagation()}>
            <div className="px-4 py-3 border-b border-border flex items-center justify-between bg-surface-2">
              <span className="text-xs font-mono text-info">{editing}</span>
              <div className="flex gap-2">
                <button onClick={() => run(editing)}
                  className="px-3 py-1 rounded text-[11px] bg-pass/20 text-pass hover:bg-pass/30">▶ 执行</button>
                <button onClick={save}
                  className="px-3 py-1 rounded text-[11px] bg-info/20 text-info hover:bg-info/30">💾 保存</button>
                <button onClick={() => setEditing(null)} className="text-gray-500 hover:text-gray-300 px-1">✕</button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] text-gray-500 mb-0.5">名称</label>
                  <input value={editData.name || ''} onChange={(e) => setEditData({ ...editData, name: e.target.value })}
                    className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-xs" />
                </div>
                <div>
                  <label className="block text-[10px] text-gray-500 mb-0.5">环境</label>
                  <select value={editData.env || 'sit'} onChange={(e) => setEditData({ ...editData, env: e.target.value })}
                    className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-xs">
                    <option value="sit">SIT</option>
                    <option value="uat">UAT</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-[10px] text-gray-500 mb-0.5">描述</label>
                <input value={editData.description || ''} onChange={(e) => setEditData({ ...editData, description: e.target.value })}
                  className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-xs" />
              </div>

              {/* 断点设置 */}
              <div>
                <div className="text-[11px] text-gray-400 font-medium mb-2">
                  🔴 断点设置（在选中的场景前暂停执行）
                </div>
                <div className="flex flex-wrap gap-1">
                  {((editData.filter?.scenarios || []) as string[]).map((sid) => {
                    const bps = (editData.breakpoints || []) as string[];
                    const isBp = bps.includes(sid);
                    return (
                      <button key={sid}
                        onClick={() => {
                          const next = isBp ? bps.filter((b) => b !== sid) : [...bps, sid];
                          setEditData({ ...editData, breakpoints: next });
                        }}
                        className={`text-[10px] font-mono px-1.5 py-0.5 rounded transition-colors ${
                          isBp ? 'bg-fail/20 text-fail border border-fail/40' : 'bg-surface-3 text-gray-500 hover:text-gray-300'
                        }`}>
                        {isBp ? '🔴 ' : ''}{sid}
                      </button>
                    );
                  })}
                </div>
                {((editData.breakpoints || []) as string[]).length > 0 && (
                  <p className="text-[10px] text-gray-600 mt-1">
                    执行到 {((editData.breakpoints || []) as string[]).map((b) => `🔴${b}`).join('、')} 前将暂停，人工确认后放行
                  </p>
                )}
              </div>

              {/* 场景选择 */}
              <div>
                <div className="text-[11px] text-gray-400 font-medium mb-2">
                  场景选择（{(editData.filter?.scenarios || []).length} 个）
                </div>
                <div className="grid grid-cols-2 gap-1 max-h-64 overflow-y-auto border border-border/30 rounded-lg p-2">
                  {scenarios.map((s) => {
                    const checked = ((editData.filter?.scenarios || []) as string[]).includes(s.id);
                    return (
                      <label key={s.id}
                        className={`flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-pointer transition-colors ${
                          checked ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
                        }`}>
                        <input type="checkbox" checked={checked} onChange={() => toggleScenario(s.id)} />
                        <span className="font-mono text-[10px]">{s.id}</span>
                        <span className="truncate text-[10px] text-gray-500">{s.title}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              {/* 历史记录 */}
              {history.length > 0 && (
                <div>
                  <div className="text-[11px] text-gray-400 font-medium mb-2">执行历史</div>
                  <div className="space-y-1">
                    {history.map((h) => (
                      <div key={h.run_id} className="flex items-center gap-3 text-xs px-2 py-1.5 bg-surface-2 rounded">
                        <span className="font-mono text-gray-400">{h.run_id}</span>
                        <span className="text-gray-500">{h.env}</span>
                        <span className="text-pass">✓{h.stats?.pass}</span>
                        <span className="text-fail">✗{h.stats?.fail}</span>
                        <span className="text-skip">⊘{h.stats?.skip}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
