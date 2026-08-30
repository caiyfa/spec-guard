/** StepFormCard — 紧凑步骤卡片（折叠/展开）
 *
 * 折叠态：一行显示类型 + 关键信息 + save 输出
 * 展开态：完整表单字段 + VariablePopover 角标
 */
import React, { useState } from 'react';
import VariablePopover, { type LocalVar } from './VariablePopover';
import { SqlResultTable } from './SqlResultTable';
import { dbApi } from '../api/db';
import type { DbQueryResult } from '../api/db';
import type { EmpRole, UpstreamVar, EnvVar } from '../api';

export interface StepData {
  type: string;
  body: Record<string, unknown>;
}

interface Props {
  step: StepData;
  index: number;
  empRoles: EmpRole[];
  accounts: string[];
  localVars: LocalVar[];
  upstreamVars: UpstreamVar[];
  envVars: EnvVar[];
  onChange: (index: number, step: StepData) => void;
  onRemove: (index: number) => void;
  onMoveUp: (index: number) => void;
  onMoveDown: (index: number) => void;
}

const STEP_META: Record<string, { icon: string; label: string }> = {
  select_emp: { icon: '👤', label: '工号池' },
  fetch_permission: { icon: '🔐', label: '权限预言' },
  call: { icon: '🌐', label: 'HTTP' },
  poll: { icon: '🔄', label: '轮询' },
  random: { icon: '🎲', label: '随机' },
  oss_upload: { icon: '📤', label: 'OSS上传' },
  oss_download: { icon: '📥', label: 'OSS下载' },
  set_var: { icon: '📝', label: '变量' },
  db_query: { icon: '🗄', label: 'SQL' },
  python: { icon: '🐍', label: 'Python' },
};

export default function StepFormCard({
  step, index, empRoles, accounts, localVars, upstreamVars, envVars,
  onChange, onRemove, onMoveUp, onMoveDown,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const b = step.body;
  // 编辑态试跑（设计 2026-08-25 §A4 入口①）——不含运行时 save 变量，env.* 由后端插值
  const [tryout, setTryout] = useState<{ loading: boolean; result?: DbQueryResult; error?: string } | null>(null);

  const runTryout = async () => {
    const sqlText = String(b.sql || '');
    setTryout({ loading: true });
    try {
      const r = await dbApi.query({ sql: sqlText, schema: String(b.schema || '') || undefined, vars: {} });
      setTryout({ loading: false, result: r });
    } catch (e: any) {
      // 插值失败（引用运行时变量）→ 诚实提示变量名；守卫拒绝 → 显示文案
      setTryout({ loading: false, error: e.message || '试跑失败' });
    }
  };
  const set = (key: string, value: unknown) =>
    onChange(index, { ...step, body: { ...b, [key]: value } });

  const meta = STEP_META[step.type] || { icon: '⚙️', label: step.type };
  const saveName = (b.save as string) || '';

  // 折叠态摘要
  const summary = buildSummary(step);

  const vp = (onInsert: (t: string) => void) => (
    <VariablePopover localVars={localVars} upstreamVars={upstreamVars} envVars={envVars} onInsert={onInsert} />
  );

  return (
    <div className={`border rounded-lg overflow-hidden transition-colors ${expanded ? 'border-info/40 bg-surface-2' : 'border-border/50 bg-surface-2/50'}`}>
      {/* ── 折叠头 ── */}
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-surface-3/50"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-fs-aux text-gray-600 w-4">{index + 1}</span>
        <span>{meta.icon}</span>
        <span className="text-[11px] font-medium text-gray-300">{meta.label}</span>
        <span className="text-fs-aux text-gray-500 truncate flex-1">{summary}</span>
        {saveName && (
          <code className="text-fs-aux font-mono text-pass/70 bg-pass/10 px-1.5 rounded">→ {saveName}</code>
        )}
        <span className="text-gray-600 text-fs-aux">{expanded ? '▾' : '▸'}</span>
      </div>

      {/* ── 展开表单 ── */}
      {expanded && (
        <div className="border-t border-border/30 p-3 space-y-2.5">
          {/* 类型选择 */}
          <div className="flex items-center gap-2">
            <span className="text-fs-aux text-gray-500">类型</span>
            <select
              value={step.type}
              onChange={(e) => onChange(index, { type: e.target.value, body: { save: b.save } })}
              className="bg-surface-3 border border-border rounded px-1.5 py-0.5 text-[11px]"
            >
              {Object.entries(STEP_META).map(([k, v]) => <option key={k} value={k}>{v.icon} {v.label}</option>)}
            </select>
            <div className="ml-auto flex gap-0.5">
              <MiniBtn onClick={() => onMoveUp(index)} title="上移">↑</MiniBtn>
              <MiniBtn onClick={() => onMoveDown(index)} title="下移">↓</MiniBtn>
              <MiniBtn onClick={() => onRemove(index)} title="删除" danger>✕</MiniBtn>
            </div>
          </div>

          {/* ── select_emp ── */}
          {step.type === 'select_emp' && (
            <>
              <Row label="角色" required>
                <select value={(b.role as string) || ''} onChange={(e) => set('role', e.target.value)}
                  className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-[11px]">
                  <option value="">选择…</option>
                  {empRoles.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
                </select>
              </Row>
              <Row label="独占">
                <label className="flex items-center gap-1 text-[11px] text-gray-400">
                  <input type="checkbox" checked={!!b.exclusive}
                    onChange={(e) => set('exclusive', e.target.checked || undefined)} />
                  exclusive
                </label>
              </Row>
            </>
          )}

          {/* ── fetch_permission ── */}
          {step.type === 'fetch_permission' && (
            <Row label="账号" required>
              <select value={(b.account as string) || 'default'} onChange={(e) => set('account', e.target.value)}
                className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-[11px]">
                {accounts.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </Row>
          )}

          {/* ── call（Apifox 风格：Headers/Cookies/Body 类型） ── */}
          {step.type === 'call' && (
            <>
              <div className="flex gap-2">
                <Row label="账号" className="w-20">
                  <select value={(b.as as string) || 'default'} onChange={(e) => set('as', e.target.value)}
                    className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]">
                    {accounts.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </Row>
                <Row label="方法" className="w-20">
                  <select value={(b.method as string) || 'GET'} onChange={(e) => set('method', e.target.value)}
                    className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]">
                    {['GET', 'POST', 'PUT', 'DELETE'].map((m) => <option key={m}>{m}</option>)}
                  </select>
                </Row>
                <Row label="路径" required className="flex-1">
                  <VarInput value={(b.path as string) || ''} onChange={(v) => set('path', v)}
                    placeholder="/api/…" vp={vp((t) => set('path', ((b.path as string) || '') + t))} />
                </Row>
              </div>
              <KVEditor label="Query" value={(b.params as Record<string, string>) || {}}
                onChange={(v) => set('params', v)} vp={vp} />
              <KVEditor label="Headers" value={(b.headers as Record<string, string>) || {}}
                onChange={(v) => set('headers', v)} vp={vp} />
              <KVEditor label="Cookies" value={(b.cookies as Record<string, string>) || {}}
                onChange={(v) => set('cookies', v)} vp={vp} />
              <Row label="Body 类型">
                <select value={(b.body_type as string) || 'json'}
                  onChange={(e) => set('body_type', e.target.value === 'json' ? undefined : e.target.value)}
                  className="bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]">
                  {['json', 'form', 'urlencoded', 'raw', 'binary'].map((t) => <option key={t}>{t}</option>)}
                </select>
              </Row>
              {((b.body_type as string) || 'json') === 'json' && (
                <KVEditor label="Body (json)" value={(b.json as Record<string, unknown>) || {}}
                  onChange={(v) => set('json', v)} vp={vp} />
              )}
              {(b.body_type as string) === 'form' && (
                <KVEditor label="Form（值以 @ 开头=文件上传字段）" value={(b.form as Record<string, unknown>) || {}}
                  onChange={(v) => set('form', v)} vp={vp} />
              )}
              {(b.body_type as string) === 'urlencoded' && (
                <KVEditor label="Urlencoded" value={(b.urlencoded as Record<string, unknown>) || {}}
                  onChange={(v) => set('urlencoded', v)} vp={vp} />
              )}
              {(b.body_type as string) === 'raw' && (
                <>
                  <Row label="Raw 文本">
                    <textarea value={(b.raw as string) || ''} onChange={(e) => set('raw', e.target.value)}
                      rows={3} placeholder="原始文本 body"
                      className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono" />
                  </Row>
                  <Row label="Content-Type">
                    <input value={(b.content_type as string) || 'text/plain'}
                      onChange={(e) => set('content_type', e.target.value)}
                      className="w-48 bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono" />
                  </Row>
                </>
              )}
              {(b.body_type as string) === 'binary' && (
                <Row label="文件路径" required>
                  <VarInput value={(b.file as string) || ''} onChange={(v) => set('file', v)}
                    placeholder="test-data/附件.xlsx" vp={vp((t) => set('file', ((b.file as string) || '') + t))} />
                </Row>
              )}
            </>
          )}

          {/* ── random ── */}
          {step.type === 'random' && (
            <>
              <Row label="类型" required>
                <select value={(b.type as string) || 'number'} onChange={(e) => set('type', e.target.value)}
                  className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]">
                  <option value="number">随机整数</option>
                  <option value="float">随机浮点数</option>
                  <option value="text">随机文本（词库）</option>
                  <option value="uuid">UUID</option>
                  <option value="pick">自定义选取</option>
                </select>
              </Row>
              {((b.type as string) === 'number' || (b.type as string) === 'float' || !(b.type as string)) && (
                <div className="grid grid-cols-2 gap-2">
                  <Row label="最小值">
                    <input type="number" value={(b.min as number) || 1} onChange={(e) => set('min', Number(e.target.value))}
                      className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]" />
                  </Row>
                  <Row label="最大值">
                    <input type="number" value={(b.max as number) || 100} onChange={(e) => set('max', Number(e.target.value))}
                      className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]" />
                  </Row>
                </div>
              )}
              {(b.type as string) === 'text' && (
                <>
                  <Row label="词库" required>
                    <select value={(b.pool as string) || ''} onChange={(e) => set('pool', e.target.value)}
                      className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]">
                      <option value="">选择词库…</option>
                      <option value="activity_name">盘点活动名</option>
                      <option value="department">部门名</option>
                      <option value="person_name">姓名</option>
                      <option value="eval_text">评价文本</option>
                      <option value="session_desc">会话描述</option>
                      <option value="tag">标签</option>
                    </select>
                  </Row>
                  <Row label="随机后缀">
                    <label className="flex items-center gap-1 text-[11px] text-gray-400">
                      <input type="checkbox" checked={!!b.suffix}
                        onChange={(e) => set('suffix', e.target.checked || undefined)} />
                      加随机数字后缀（如"张超-482"）
                    </label>
                  </Row>
                </>
              )}
              {(b.type as string) === 'pick' && (
                <Row label="选项列表" required>
                  <input value={((b.items as string[]) || []).join(', ')}
                    onChange={(e) => set('items', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))}
                    placeholder="选项1, 选项2, 选项3"
                    className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-[11px]" />
                </Row>
              )}
            </>
          )}

          {/* ── poll ── */}
          {step.type === 'poll' && (
            <>
              <div className="text-fs-aux text-gray-500 bg-surface-3/50 rounded px-2 py-1.5">
                轮询配置（call + until 条件需通过 YAML 模式编辑）
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Row label="间隔(ms)">
                  <input type="number" value={(b.interval_ms as number) || 2000}
                    onChange={(e) => set('interval_ms', Number(e.target.value))}
                    className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]" />
                </Row>
                <Row label="超时(ms)">
                  <input type="number" value={(b.timeout_ms as number) || 60000}
                    onChange={(e) => set('timeout_ms', Number(e.target.value))}
                    className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]" />
                </Row>
                <Row label="超时处理">
                  <select value={(b.on_timeout as string) || 'fail'}
                    onChange={(e) => set('on_timeout', e.target.value)}
                    className="w-full bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px]">
                    <option value="fail">fail</option>
                    <option value="skip">skip</option>
                  </select>
                </Row>
              </div>
            </>
          )}

          {/* ── oss_upload ── */}
          {step.type === 'oss_upload' && (
            <>
              <Row label="文件路径" required>
                <VarInput value={(b.file as string) || ''} onChange={(v) => set('file', v)}
                  placeholder="test-data/盘点表.xlsx" vp={vp((t) => set('file', ((b.file as string) || '') + t))} />
              </Row>
              <Row label="租户">
                <input value={(b.tenant as string) || 'COREHR'} onChange={(e) => set('tenant', e.target.value)}
                  className="w-28 bg-surface-3 border border-border rounded px-2 py-1 text-[11px]" />
              </Row>
            </>
          )}

          {/* ── oss_download ── */}
          {step.type === 'oss_download' && (
            <>
              <Row label="ossKey" required>
                <VarInput value={(b.ossKey as string) || ''} onChange={(v) => set('ossKey', v)}
                  placeholder="{{upload.ossKey}}" vp={vp((t) => set('ossKey', ((b.ossKey as string) || '') + t))} />
              </Row>
              <Row label="输出目录">
                <input value={(b.output_dir as string) || 'downloads'} onChange={(e) => set('output_dir', e.target.value)}
                  className="w-28 bg-surface-3 border border-border rounded px-2 py-1 text-[11px]" />
              </Row>
            </>
          )}

          {/* ── set_var ── */}
          {step.type === 'set_var' && (
            <KVEditor label="变量" value={(b.vars as Record<string, string>) || {}}
              onChange={(v) => set('vars', v)} vp={vp} />
          )}

          {/* ── db_query ── */}
          {step.type === 'db_query' && (
            <>
            <Row label="SQL" required>
              <textarea value={(b.sql as string) || ''} onChange={(e) => set('sql', e.target.value)}
                rows={2} placeholder="SELECT …"
                className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono" />
            </Row>
            <div className="flex items-center gap-2 mt-1">
              <button type="button" onClick={runTryout} disabled={tryout?.loading}
                className="text-fs-aux px-2 py-0.5 rounded border border-info/40 text-info hover:bg-info/10 disabled:opacity-50"
                title="编辑态试跑（不含运行时 save 变量；env.* 由后端插值）">
                ▶ 试跑
              </button>
              <span className="text-fs-aux text-gray-600">编辑态试跑不含运行时变量</span>
            </div>
            {tryout && (
              <div className="mt-1 border border-border rounded p-2 bg-surface-2">
                {tryout.loading && <div className="text-xs text-gray-500">查询中…</div>}
                {tryout.error && <div className="text-xs text-red-400">❌ {tryout.error}</div>}
                {tryout.result && <SqlResultTable rows={tryout.result.rows} row_count={tryout.result.row_count} truncated={tryout.result.truncated} />}
                <button type="button" onClick={() => setTryout(null)} className="text-fs-aux text-gray-500 hover:text-gray-300 mt-1">关闭</button>
              </div>
            )}
            </>
          )}

          {/* ── python ── */}
          {step.type === 'python' && (
            <>
              <Row label="Python 脚本" required>
                <textarea value={(b.script as string) || ''} onChange={(e) => set('script', e.target.value)}
                  rows={7} placeholder={"rows = ns['rows']\noutput = [r for r in rows if r['score'] is None]\nprint(f'过滤出 {len(output)} 行')"}
                  className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono leading-snug" />
              </Row>
              <div className="text-fs-aux text-gray-600 bg-surface-3/40 rounded px-2 py-1.5 space-y-0.5">
                <div>可用：<code className="text-info/70">ns</code>（读写变量）、<code className="text-info/70">save(k,v)</code>、<code className="text-info/70">output</code>（配合 save 输出）、<code className="text-info/70">http(account)</code>、<code className="text-info/70">db</code>、<code className="text-info/70">fn.date()</code>、<code className="text-info/70">json/re/time/datetime/uuid</code></div>
              </div>
            </>
          )}

          {/* ── save 输出 ── */}
          <div className="border-t border-border/20 pt-2 mt-1">
            <Row label="输出 save" required>
              <input value={saveName} onChange={(e) => set('save', e.target.value || undefined)}
                placeholder="变量名"
                className="w-32 bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono text-pass" />
              {saveName && <OutputHints type={step.type} name={saveName} />}
            </Row>
          </div>
        </div>
      )}
    </div>
  );
}

/** 折叠态摘要文字 */
function buildSummary(step: StepData): string {
  const b = step.body;
  switch (step.type) {
    case 'select_emp': return String(b.role || '');
    case 'fetch_permission': return String(b.account || 'default');
    case 'call': return `${b.method || 'GET'} ${b.path || ''}`;
    case 'oss_upload': return `📤 ${b.file || ''}`;
    case 'oss_download': return `📥 ${b.ossKey || ''}`;
    case 'poll': return `🔄 ${((b.call as Record<string, unknown>) || {}).method || 'GET'} ${((b.call as Record<string, unknown>) || {}).path || ''}`;
    case 'random': return `🎲 ${b.type || 'number'}${b.pool ? `:${b.pool}` : ''}`;
    case 'set_var': return Object.keys((b.vars as Record<string, unknown>) || {}).join(', ');
    case 'db_query': return String(b.note || (b.sql as string || '').slice(0, 40));
    case 'python': return `🐍 ${(b.script as string || '').split('\n')[0].slice(0, 40)}`;
    default: return '';
  }
}

/** 输出变量提示 */
function OutputHints({ type, name }: { type: string; name: string }) {
  const hints: Record<string, string[]> = {
    select_emp: ['.no', '.activity_id', '.session_id'],
    call: ['.status', '.json'],
    fetch_permission: ['.corp_codes', '.has_any'],
    oss_upload: ['.ossKey', '.fileName', '.fileSize'],
    oss_download: ['.file_path', '.file_size', '.fileName'],
    poll: ['.status', '.json'],
  };
  const paths = hints[type];
  if (!paths) return null;
  return (
    <span className="ml-2 text-fs-aux text-gray-600">
      {paths.map((p) => <code key={p} className="mr-1 text-pass/50">{`{{${name}${p}}}`}</code>)}
    </span>
  );
}

/** 带变量角标的输入框 */
function VarInput({ value, onChange, placeholder, vp }: {
  value: string; onChange: (v: string) => void; placeholder?: string; vp: React.ReactNode;
}) {
  return (
    <div className="flex items-center flex-1">
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono" />
      {vp}
    </div>
  );
}

/** Key-Value 编辑器 */
function KVEditor({ label, value, onChange, vp }: {
  label: string;
  value: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
  vp: (onInsert: (t: string) => void) => React.ReactNode;
}) {
  const entries = Object.entries(value);
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <span className="text-fs-aux text-gray-500">{label}</span>
        <button onClick={() => onChange({ ...value, '': '' })}
          className="text-fs-aux text-gray-600 hover:text-info">+ 添加</button>
      </div>
      {entries.map(([k, v], i) => (
        <div key={i} className="flex items-center gap-1 mb-1">
          <input value={k} placeholder="key"
            onChange={(e) => {
              const ne = [...entries]; ne[i] = [e.target.value, v];
              onChange(Object.fromEntries(ne));
            }}
            className="w-24 bg-surface-3 border border-border/50 rounded px-1.5 py-0.5 text-fs-aux font-mono" />
          <span className="text-gray-600 text-fs-aux">=</span>
          <VarInput value={String(v ?? '')} onChange={(val) => {
            const ne = [...entries]; ne[i] = [k, val];
            onChange(Object.fromEntries(ne));
          }} vp={vp((t) => {
            const ne = [...entries]; ne[i] = [k, String(v ?? '') + t];
            onChange(Object.fromEntries(ne));
          })} />
          <button onClick={() => onChange(Object.fromEntries(entries.filter((_, j) => j !== i)))}
            className="text-gray-600 hover:text-fail text-fs-aux">✕</button>
        </div>
      ))}
    </div>
  );
}

/** 行布局 */
function Row({ label, required, className, children }: {
  label: string; required?: boolean; className?: string; children: React.ReactNode;
}) {
  return (
    <div className={className}>
      <label className="block text-fs-aux text-gray-500 mb-0.5">
        {label}{required && <span className="text-fail">*</span>}
      </label>
      <div className="flex items-center">{children}</div>
    </div>
  );
}

/** 小按钮 */
function MiniBtn({ onClick, title, danger, children }: {
  onClick: () => void; title: string; danger?: boolean; children: React.ReactNode;
}) {
  return (
    <button onClick={(e) => { e.stopPropagation(); onClick(); }} title={title}
      className={`text-fs-aux px-1 py-0.5 rounded ${danger ? 'text-gray-600 hover:text-fail' : 'text-gray-600 hover:text-info'}`}>
      {children}
    </button>
  );
}
