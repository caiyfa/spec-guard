/** ScenarioFormEditor — 场景编辑器（Tab 分区 + 阅读/表单/YAML 三模式）
 *
 * 参考 Apifox 场景编排：
 * - Tab 分区聚焦：基本信息 / 依赖与产出 / 执行步骤 / 断言 / 清理
 * - 步骤卡片紧凑折叠，展开后才显示完整表单
 * - 变量通过 {x} 角标弹出，不平铺
 * - 阅读（T-1023 ScenarioReader 只读）/表单/YAML 三模式可互切
 */
import React, { useEffect, useMemo, useState } from 'react';
import { load as yamlLoad, dump as yamlDump } from 'js-yaml';
import Editor from '@monaco-editor/react';
import StepFormCard, { type StepData } from './StepFormCard';
import ScenarioReader from './ScenarioReader';
import type { LocalVar } from './VariablePopover';
import type { EmpRole, OracleRef, UpstreamVar, EnvVar, ScenarioDetail } from '../api';
import { referenceApi } from '../api';
import { useJsTokens } from '../theme';

interface Props {
  scenarioId: string;
  yamlContent: string;
  empRoles: EmpRole[];
  oracles: OracleRef[];
  upstreamVars: UpstreamVar[];
  envVars: EnvVar[];
  allScenarios: { id: string; title: string }[];
  onSave: (yaml: string) => Promise<void>;
}

type TabKey = 'info' | 'deps' | 'flow' | 'verify' | 'teardown';

/** tool 信封类型集合（格式 2.0：领域步骤在 YAML 中以 tool: {use, with, save} 存储） */
const TOOL_TYPES = new Set(['select_emp', 'fetch_permission', 'oss_upload', 'oss_download', 'random', 'set_var']);

/** 拆封 tool 信封：YAML {tool: {use, with, save}} → 表单 {type, body（含 save）} */
function unwrapStep(step: Record<string, Record<string, unknown>>): StepData {
  const [type, body] = Object.entries(step)[0] || ['call', {}];
  if (type === 'tool' && body && typeof body === 'object') {
    const b = body as { use?: string; with?: Record<string, unknown>; save?: string };
    if (b.use) {
      return { type: b.use, body: { ...(b.with || {}), ...(b.save ? { save: b.save } : {}) } };
    }
  }
  return { type, body: body || {} };
}

/** 还原 tool 信封：表单 {type, body} → YAML {tool: {use, with?, save?}}；原语（call/db_query/poll）直出 */
function wrapStep(s: StepData): Record<string, unknown> {
  if (TOOL_TYPES.has(s.type)) {
    const { save, ...rest } = (s.body || {}) as Record<string, unknown>;
    const toolBody: Record<string, unknown> = { use: s.type };
    if (Object.keys(rest).length) toolBody.with = rest;
    if (save) toolBody.save = save;
    return { tool: toolBody };
  }
  return { [s.type]: s.body };
}

/** 依赖项（表单态）：version/optional 必须透传，否则表单保存会丢数据 */
interface DepItem { id: string; mode: string; version?: string; optional: boolean }

/** 依赖序列化：仅当纯 shared 且无 version/optional 时退化为字符串简写，其余保持 dict 完整形态 */
function serializeDeps(items: DepItem[]): (string | Record<string, unknown>)[] {
  return items.map((x) => {
    if (x.mode === 'shared' && !x.version && !x.optional) return x.id;
    const d: Record<string, unknown> = { id: x.id };
    if (x.mode !== 'shared') d.mode = x.mode;
    if (x.version) d.version = x.version;
    if (x.optional) d.optional = true;
    return d;
  });
}

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: 'info', label: '基本信息', icon: '📋' },
  { key: 'deps', label: '依赖与产出', icon: '🔗' },
  { key: 'flow', label: '执行步骤', icon: '▶️' },
  { key: 'verify', label: '断言', icon: '✅' },
  { key: 'teardown', label: '清理', icon: '🧹' },
];

export default function ScenarioFormEditor({
  scenarioId, yamlContent, empRoles, oracles, upstreamVars, envVars, allScenarios, onSave,
}: Props) {
  const [data, setData] = useState<Record<string, unknown>>({});
  const [yamlText, setYamlText] = useState('');
  const [tab, setTab] = useState<TabKey>('flow');
  const [mode, setMode] = useState<'read' | 'form' | 'yaml'>('form');
  const tokens = useJsTokens();  // K-043：Monaco 主题跟随
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');

  // 初始化：解析 YAML
  useEffect(() => {
    setYamlText(yamlContent);
    try {
      setData((yamlLoad(yamlContent) as Record<string, unknown>) || {});
    } catch { setData({}); }
  }, [yamlContent]);

  const update = (key: string, value: unknown) => setData((prev) => ({ ...prev, [key]: value }));

  // ── 模式切换 ──
  const switchMode = (m: 'read' | 'form' | 'yaml') => {
    if (m === 'yaml') {
      // form/read → yaml：序列化当前 data 到编辑器
      try { setYamlText(yamlDump(data, { indent: 2, lineWidth: 120, noRefs: true })); } catch { /* */ }
    } else if (m === 'read' && mode === 'form') {
      // form → read：表单编辑只改了 data，刷新 yamlText 保持阅读视图与表单一致
      try { setYamlText(yamlDump(data, { indent: 2, lineWidth: 120, noRefs: true })); } catch { /* */ }
    } else {
      // yaml → form/read：解析编辑器内容回 data
      try { setData((yamlLoad(yamlText) as Record<string, unknown>) || {}); } catch { /* */ }
    }
    setMode(m);
  };

  // ── flow 步骤 ──
  const flowSteps = useMemo<StepData[]>(() => {
    const flow = (data.flow as Record<string, Record<string, unknown>>[]) || [];
    return flow.map(unwrapStep);
  }, [data.flow]);

  const setFlowSteps = (steps: StepData[]) =>
    update('flow', steps.map(wrapStep));

  // ── teardown 步骤 ──
  const teardownSteps = useMemo<StepData[]>(() => {
    const td = (data.teardown as Record<string, Record<string, unknown>>[]) || [];
    return td.map(unwrapStep);
  }, [data.teardown]);

  const setTeardownSteps = (steps: StepData[]) =>
    update('teardown', steps.map(wrapStep));

  // ── verify 断言 ──
  const verifyItems = useMemo(() => (data.verify as Record<string, unknown>[]) || [], [data.verify]);
  const setVerifyItems = (items: Record<string, unknown>[]) => update('verify', items);

  // ── depends_on ──
  const deps = useMemo<DepItem[]>(() => {
    const raw = (data.depends_on as (string | Record<string, unknown>)[]) || [];
    return raw.map((d) => (typeof d === 'string'
      ? { id: d, mode: 'shared', version: undefined, optional: false }
      : { id: String(d.id || ''), mode: String(d.mode || 'shared'),
          version: d.version as string | undefined, optional: !!d.optional }));
  }, [data.depends_on]);

  // ── produces ──
  const produces = useMemo(() => (data.produces as Record<string, string>[]) || [], [data.produces]);

  // ── 已 save 的变量 ──
  const localVars = useMemo<LocalVar[]>(() =>
    flowSteps.filter((s) => s.body.save).map((s) => ({ saveName: String(s.body.save), stepType: s.type })),
    [flowSteps],
  );

  const accounts = ['default', 'no_access', 'restricted', 'none'];
  const doc = (data.doc as Record<string, unknown>) || {};

  // ── 保存 ──
  const save = async () => {
    setSaving(true); setSaveMsg('');
    try {
      const yamlStr = mode === 'yaml'
        ? yamlText
        : yamlDump(data, { indent: 2, lineWidth: 120, noRefs: true });
      await onSave(yamlStr);
      setSaveMsg('✓ 已保存');
    } catch (e: unknown) {
      setSaveMsg(`✗ ${e instanceof Error ? e.message : '保存失败'}`);
    } finally { setSaving(false); }
  };

  return (
    <div className="h-full flex flex-col">
      {/* ── 顶栏：场景 ID + 模式切换 + 保存 ── */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-surface-2 flex-shrink-0">
        <span className="text-xs font-mono text-info">{scenarioId}</span>
        <div className="flex items-center gap-2">
          <div className="flex bg-surface-3 rounded overflow-hidden">
            {(['read', 'form', 'yaml'] as const).map((m) => (
              <button key={m} onClick={() => switchMode(m)}
                className={`px-2.5 py-1 text-[10px] transition-colors ${mode === m ? 'bg-info/20 text-info' : 'text-gray-500 hover:text-gray-300'}`}>
                {m === 'read' ? '📖 阅读' : m === 'form' ? '📋 表单' : '📄 YAML'}
              </button>
            ))}
          </div>
          {mode !== 'read' && (
            <button onClick={save} disabled={saving}
              className="px-3 py-1 rounded text-[11px] bg-pass/20 text-pass hover:bg-pass/30 disabled:opacity-40">
              {saving ? '…' : '💾 保存'}
            </button>
          )}
        </div>
      </div>
      {saveMsg && mode !== 'read' && <div className={`px-3 py-1 text-[11px] flex-shrink-0 ${saveMsg.startsWith('✓') ? 'text-pass' : 'text-fail'}`}>{saveMsg}</div>}

      {/* ── 阅读模式（T-1023 只读结构化视图） ── */}
      {mode === 'read' && (
        <div className="flex-1 min-h-0">
          <ScenarioReader data={data} rawYaml={yamlText} filePath={scenarioId} />
        </div>
      )}

      {/* ── YAML 模式 ── */}
      {mode === 'yaml' && (
        <div className="flex-1 min-h-0">
          <Editor language="yaml" theme={tokens.monaco} value={yamlText}
            onChange={(v) => setYamlText(v || '')}
            options={{ fontSize: 12, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false }} />
        </div>
      )}

      {/* ── 表单模式 ── */}
      {mode === 'form' && (
        <>
          {/* Tab 栏 */}
          <div className="flex border-b border-border bg-surface-2 flex-shrink-0">
            {TABS.map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={`flex-1 py-2 text-[11px] text-center transition-colors ${
                  tab === t.key
                    ? 'text-info border-b-2 border-info bg-surface-3/50 font-medium'
                    : 'text-gray-500 hover:text-gray-300'
                }`}>
                {t.icon} {t.label}
                {t.key === 'flow' && flowSteps.length > 0 && <span className="ml-1 text-[9px] text-gray-600">({flowSteps.length})</span>}
                {t.key === 'verify' && verifyItems.length > 0 && <span className="ml-1 text-[9px] text-gray-600">({verifyItems.length})</span>}
                {t.key === 'teardown' && teardownSteps.length > 0 && <span className="ml-1 text-[9px] text-gray-600">({teardownSteps.length})</span>}
              </button>
            ))}
          </div>

          {/* Tab 内容 */}
          <div className="flex-1 overflow-y-auto p-3">

            {/* ═══ 基本信息 ═══ */}
            {tab === 'info' && (
              <div className="space-y-3 max-w-lg">
                <div className="grid grid-cols-2 gap-3">
                  <F label="ID"><input value={String(data.id || '')} readOnly className="w-full bg-surface-3/50 border border-border/50 rounded px-2 py-1.5 text-xs font-mono text-gray-500" /></F>
                  <F label="标题"><input value={String(data.title || '')} onChange={(e) => update('title', e.target.value)} className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-xs" /></F>
                  <F label="优先级">
                    <select value={String(data.priority || 'P1')} onChange={(e) => update('priority', e.target.value)} className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-xs">
                      {['P0', 'P1', 'P2'].map((p) => <option key={p}>{p}</option>)}
                    </select>
                  </F>
                  <F label="标签">
                    <input value={((data.tags as string[]) || []).join(', ')} onChange={(e) => update('tags', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))}
                      placeholder="resolver, permission" className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-xs" />
                  </F>
                </div>
                <div className="border-t border-border/30 pt-3">
                  <div className="text-[11px] text-gray-400 font-medium mb-2">人读层（doc）</div>
                  {(['given', 'when', 'then'] as const).map((k) => (
                    <F key={k} label={k}>
                      <input value={String(doc[k] || '')} onChange={(e) => update('doc', { ...doc, [k]: e.target.value })}
                        className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-xs" />
                    </F>
                  ))}
                  <F label="覆盖 FR">
                    <input value={((doc.covers as string[]) || []).join(', ')} onChange={(e) => update('doc', { ...doc, covers: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
                      placeholder="FR-001, FR-002" className="w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-xs font-mono" />
                  </F>
                </div>
              </div>
            )}

            {/* ═══ 依赖与产出 ═══ */}
            {tab === 'deps' && (
              <div className="space-y-4 max-w-xl">
                <div>
                  <div className="text-[11px] text-gray-400 font-medium mb-2">依赖（depends_on）</div>
                  {deps.map((d, i) => (
                    <DepRow key={`${d.id}-${i}`} dep={d}
                      allScenarios={allScenarios} scenarioId={scenarioId}
                      onChange={(nd) => {
                        const newDeps = [...deps]; newDeps[i] = nd;
                        update('depends_on', serializeDeps(newDeps));
                      }}
                      onRemove={() => update('depends_on', serializeDeps(deps.filter((_, j) => j !== i)))}
                    />
                  ))}
                  <button onClick={() => update('depends_on', serializeDeps([...deps, { id: '', mode: 'shared', version: undefined, optional: false }]))}
                    className="text-[10px] text-gray-500 hover:text-info">+ 添加依赖</button>
                </div>
                <div className="border-t border-border/30 pt-3">
                  <div className="text-[11px] text-gray-400 font-medium mb-2">产出声明（produces）</div>
                  {produces.map((p, i) => (
                    <div key={i} className="flex items-center gap-2 mb-1.5">
                      <input value={p.resource || ''} placeholder="资源（inv_session）"
                        onChange={(e) => { const np = [...produces]; np[i] = { ...p, resource: e.target.value }; update('produces', np); }}
                        className="flex-1 bg-surface-3 border border-border rounded px-2 py-1.5 text-xs font-mono" />
                      <input value={p.state || ''} placeholder="状态（IN_PROGRESS）"
                        onChange={(e) => { const np = [...produces]; np[i] = { ...p, state: e.target.value }; update('produces', np); }}
                        className="w-36 bg-surface-3 border border-border rounded px-2 py-1.5 text-xs font-mono" />
                      <button onClick={() => update('produces', produces.filter((_, j) => j !== i))}
                        className="text-gray-600 hover:text-fail text-xs">✕</button>
                    </div>
                  ))}
                  <button onClick={() => update('produces', [...produces, { resource: '', state: '' }])}
                    className="text-[10px] text-gray-500 hover:text-info">+ 添加产出</button>
                  <p className="text-[10px] text-gray-600 mt-1.5">声明后下游场景可感知此场景的产出资源与状态</p>
                </div>
              </div>
            )}

            {/* ═══ 执行步骤 ═══ */}
            {tab === 'flow' && (
              <div className="space-y-2">
                {flowSteps.map((step, i) => (
                  <StepFormCard key={i} step={step} index={i}
                    empRoles={empRoles} accounts={accounts}
                    localVars={flowSteps.slice(0, i).filter((s) => s.body.save).map((s) => ({ saveName: String(s.body.save), stepType: s.type }))}
                    upstreamVars={upstreamVars} envVars={envVars}
                    onChange={(idx, s) => { const ns = [...flowSteps]; ns[idx] = s; setFlowSteps(ns); }}
                    onRemove={(idx) => setFlowSteps(flowSteps.filter((_, j) => j !== idx))}
                    onMoveUp={(idx) => { if (idx > 0) { const ns = [...flowSteps]; [ns[idx-1], ns[idx]] = [ns[idx], ns[idx-1]]; setFlowSteps(ns); } }}
                    onMoveDown={(idx) => { if (idx < flowSteps.length - 1) { const ns = [...flowSteps]; [ns[idx], ns[idx+1]] = [ns[idx+1], ns[idx]]; setFlowSteps(ns); } }}
                  />
                ))}
                <button onClick={() => setFlowSteps([...flowSteps, { type: 'call', body: { method: 'GET', save: '' } }])}
                  className="w-full py-2 border border-dashed border-border/50 rounded-lg text-[11px] text-gray-500 hover:text-info hover:border-info/40">
                  + 添加步骤
                </button>
              </div>
            )}

            {/* ═══ 断言 ═══ */}
            {tab === 'verify' && (
              <div className="space-y-2 max-w-xl">
                {verifyItems.map((v, i) => (
                  <VerifyCard key={i} item={v} oracles={oracles}
                    onChange={(item) => { const nv = [...verifyItems]; nv[i] = item; setVerifyItems(nv); }}
                    onRemove={() => setVerifyItems(verifyItems.filter((_, j) => j !== i))}
                  />
                ))}
                <button onClick={() => setVerifyItems([...verifyItems, { status: { eq: 200 } }])}
                  className="w-full py-2 border border-dashed border-border/50 rounded-lg text-[11px] text-gray-500 hover:text-info hover:border-info/40">
                  + 添加断言
                </button>
              </div>
            )}

            {/* ═══ 清理 ═══ */}
            {tab === 'teardown' && (
              <div className="space-y-2">
                {teardownSteps.map((step, i) => (
                  <StepFormCard key={i} step={step} index={i}
                    empRoles={empRoles} accounts={accounts}
                    localVars={localVars}
                    upstreamVars={upstreamVars} envVars={envVars}
                    onChange={(idx, s) => { const ns = [...teardownSteps]; ns[idx] = s; setTeardownSteps(ns); }}
                    onRemove={(idx) => setTeardownSteps(teardownSteps.filter((_, j) => j !== idx))}
                    onMoveUp={(idx) => { if (idx > 0) { const ns = [...teardownSteps]; [ns[idx-1], ns[idx]] = [ns[idx], ns[idx-1]]; setTeardownSteps(ns); } }}
                    onMoveDown={(idx) => { if (idx < teardownSteps.length - 1) { const ns = [...teardownSteps]; [ns[idx], ns[idx+1]] = [ns[idx+1], ns[idx]]; setTeardownSteps(ns); } }}
                  />
                ))}
                <button onClick={() => setTeardownSteps([...teardownSteps, { type: 'call', body: { method: 'POST', save: '' } }])}
                  className="w-full py-2 border border-dashed border-border/50 rounded-lg text-[11px] text-gray-500 hover:text-info hover:border-info/40">
                  + 添加清理步骤
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** 断言卡片 */
function VerifyCard({ item, oracles, onChange, onRemove }: {
  item: Record<string, unknown>;
  oracles: OracleRef[];
  onChange: (item: Record<string, unknown>) => void;
  onRemove: () => void;
}) {
  const type = 'status' in item ? 'status' : 'oracle' in item ? 'oracle' : 'json';
  const body = (item[type] || {}) as Record<string, unknown>;

  const setType = (t: string) => {
    if (t === 'status') onChange({ status: { eq: 200 } });
    else if (t === 'oracle') onChange({ oracle: oracles[0]?.name || '' });
    else onChange({ json: { path: '$.data', eq: '' } });
  };

  const setBody = (key: string, value: unknown) => {
    onChange({ [type]: { ...body, [key]: value } });
  };

  return (
    <div className="border border-border/50 rounded-lg bg-surface-2 p-3">
      <div className="flex items-center gap-2 mb-2">
        <select value={type} onChange={(e) => setType(e.target.value)}
          className="bg-surface-3 border border-border rounded px-1.5 py-0.5 text-[11px]">
          <option value="status">status</option>
          <option value="json">json</option>
          <option value="oracle">oracle</option>
        </select>
        <button onClick={onRemove} className="ml-auto text-gray-600 hover:text-fail text-[10px]">✕</button>
      </div>
      {type === 'status' && (
        <div className="flex gap-2 items-end">
          <F label="变量"><input value={String(body.of || '')} onChange={(e) => setBody('of', e.target.value || undefined)} placeholder="最后call" className="w-20 bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px] font-mono" /></F>
          <F label="="><input type="number" value={Number(body.eq || 200)} onChange={(e) => setBody('eq', Number(e.target.value))} className="w-16 bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]" /></F>
        </div>
      )}
      {type === 'json' && (
        <div className="space-y-1.5">
          <div className="flex gap-2">
            <F label="变量" className="w-20"><input value={String(body.of || '')} onChange={(e) => setBody('of', e.target.value || undefined)} placeholder="最后call" className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px] font-mono" /></F>
            <F label="JSONPath" className="flex-1"><input value={String(body.path || '')} onChange={(e) => setBody('path', e.target.value)} placeholder="$.data.field" className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px] font-mono" /></F>
          </div>
          <div className="flex gap-2">
            <F label="操作" className="w-28">
              <select value={'eq' in body ? 'eq' : 'ne' in body ? 'ne' : 'not_null' in body ? 'not_null' : 'contains' in body ? 'contains' : 'absent' in body ? 'absent' : 'eq'}
                onChange={(e) => {
                  const op = e.target.value;
                  const base = { path: body.path, of: body.of };
                  if (op === 'eq') onChange({ json: { ...base, eq: '' } });
                  else if (op === 'ne') onChange({ json: { ...base, ne: '' } });
                  else if (op === 'not_null') onChange({ json: { ...base, not_null: true } });
                  else if (op === 'contains') onChange({ json: { ...base, contains: '' } });
                  else if (op === 'absent') onChange({ json: { ...base, absent: true } });
                }}
                className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]">
                <option value="eq">==</option><option value="ne">!=</option>
                <option value="not_null">非null</option><option value="contains">包含</option>
                <option value="absent">不存在</option>
              </select>
            </F>
            <F label="期望值" className="flex-1">
              <input value={String(body.eq ?? body.ne ?? body.contains ?? '')}
                onChange={(e) => {
                  const key = 'eq' in body ? 'eq' : 'ne' in body ? 'ne' : 'contains' in body ? 'contains' : 'eq';
                  setBody(key, e.target.value);
                }}
                className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px] font-mono" />
            </F>
          </div>
        </div>
      )}
      {type === 'oracle' && (
        <select value={String(item.oracle || '')} onChange={(e) => onChange({ oracle: e.target.value })}
          className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]">
          {oracles.map((o) => <option key={o.name} value={o.name}>{o.name} — {o.desc}</option>)}
        </select>
      )}
    </div>
  );
}

/** 依赖行：下拉选择 + 上游产出详情展示（version/optional 透传不丢失） */
function DepRow({ dep, allScenarios, scenarioId, onChange, onRemove }: {
  dep: DepItem;
  allScenarios: { id: string; title: string }[];
  scenarioId: string;
  onChange: (dep: DepItem) => void;
  onRemove: () => void;
}) {
  const [detail, setDetail] = useState<ScenarioDetail | null>(null);

  // 选中上游后加载其产出详情
  useEffect(() => {
    if (!dep.id) { setDetail(null); return; }
    referenceApi.scenarioDetail(dep.id).then(setDetail).catch(() => setDetail(null));
  }, [dep.id]);

  return (
    <div className="border border-border/40 rounded-lg bg-surface-2/50 overflow-hidden mb-1.5">
      {/* 选择行 */}
      <div className="flex items-center gap-2 px-3 py-2">
        <select value={dep.id} onChange={(e) => onChange({ ...dep, id: e.target.value })}
          className="flex-1 bg-surface-3 border border-border rounded px-2 py-1.5 text-xs">
          <option value="">选择上游场景…</option>
          {allScenarios.filter((s) => s.id !== scenarioId).map((s) => (
            <option key={s.id} value={s.id}>{s.id} — {s.title}</option>
          ))}
        </select>
        <button onClick={() => onChange({ ...dep, mode: dep.mode === 'shared' ? 'exclusive' : 'shared' })}
          className={`text-[10px] px-2 py-1 rounded border flex-shrink-0 ${dep.mode === 'exclusive' ? 'border-warn text-warn bg-warn/10' : 'border-border text-gray-500'}`}>
          {dep.mode}
        </button>
        <button onClick={onRemove} className="text-gray-600 hover:text-fail text-xs flex-shrink-0">✕</button>
      </div>

      {/* 上游产出详情 */}
      {detail && detail.id && (
        <div className="border-t border-border/30 px-3 py-2 space-y-1.5">
          {/* 场景描述 */}
          {detail.given && (
            <p className="text-[10px] text-gray-500 leading-4">📖 {detail.given}</p>
          )}

          {/* save 变量 */}
          {detail.saves.length > 0 && (
            <div>
              <span className="text-[10px] text-gray-500">产出变量：</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {detail.saves.map((s) => (
                  <span key={s.name}
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-info/10 text-info/80"
                    title={`步骤类型: ${s.step_type}`}>
                    {`{{${detail.id}.${s.name}}}`}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* produces 声明 */}
          {detail.produces.length > 0 && (
            <div>
              <span className="text-[10px] text-gray-500">资源产出：</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {detail.produces.map((p, i) => (
                  <span key={i} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-pass/10 text-pass/70">
                    {p.resource}{p.state ? `(${p.state})` : ''}
                  </span>
                ))}
              </div>
            </div>
          )}

          {detail.saves.length === 0 && detail.produces.length === 0 && (
            <p className="text-[10px] text-gray-600">该场景无 save 变量和 produces 声明</p>
          )}
        </div>
      )}
    </div>
  );
}

/** 字段标签 */
function F({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <div className={className}>
      <label className="block text-[10px] text-gray-500 mb-0.5">{label}</label>
      {children}
    </div>
  );
}
