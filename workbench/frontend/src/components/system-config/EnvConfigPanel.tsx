/** 系统配置 · 栏3：环境配置（通用配置/本系统配置 × env）+ 数据库连接
 *
 * T-1010 合并两处来源：
 * - EnvironmentConfig 页（T-306/T-309）：scope=shared 通用配置（sso/internal_token）/ scope=system 本系统配置，
 *   Monaco 编辑 raw YAML（防 js-yaml 往返丢中文注释）；
 * - Settings「数据库」tab（T-308）：结构化表单编辑 env.{env}.yaml 的 db 段 + 测试连接——
 *   迁入后 system 参数跟随栏1选中系统（原写死 tdm），env 选项跟随当前系统枚举（原硬编码 sit/uat）。
 */
import { useCallback, useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { referenceApi, type SystemInfo } from '../../api';
import { useJsTokens } from '../../theme';

type Scope = 'system' | 'shared';

const SCOPE_LABELS: Record<Scope, { label: string; hint: (sys: string) => string }> = {
  system: { label: '本系统配置', hint: (sys) => `systems/${sys}/config/env.{env}.yaml（网关/账号池/资源码，系统专属）` },
  shared: { label: '通用配置', hint: () => 'systems/_shared/config/env.{env}.yaml（跨系统复用：sso / internal_token）' },
};

interface Props {
  system: string;         // 栏1选中的系统标识
  systems: SystemInfo[];  // 系统 envs/accounts 枚举来源
  isAdmin: boolean;
}

export default function EnvConfigPanel({ system, systems, isAdmin }: Props) {
  const tokens = useJsTokens();
  const [sharedEnvNames, setSharedEnvNames] = useState<string[]>([]);
  const [currentEnv, setCurrentEnv] = useState(() => localStorage.getItem('sg_sysconf_env') || 'sit');
  const [scope, setScope] = useState<Scope>(() => (localStorage.getItem('sg_sysconf_scope') as Scope) || 'system');
  const [raw, setRaw] = useState('');
  const [parsed, setParsed] = useState<Record<string, unknown>>({});
  const [exists, setExists] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  const sysEnvs = systems.find((s) => s.name === system)?.envs || [];
  const sysAccounts = systems.find((s) => s.name === system)?.accounts || [];

  // 共享通用层环境枚举（跨系统只有一份）
  useEffect(() => {
    referenceApi.envs()
      .then((r) => setSharedEnvNames(r.shared_envs.map((e) => e.name)))
      .catch(() => {});
  }, []);

  const loadEnv = useCallback((env: string, sc: Scope, sys: string) => {
    setCurrentEnv(env);
    setScope(sc);
    localStorage.setItem('sg_sysconf_env', env);
    localStorage.setItem('sg_sysconf_scope', sc);
    if (!sys && sc === 'system') { setRaw(''); setParsed({}); setLoading(false); return; }
    setLoading(true);
    setMsg('');
    referenceApi.envConfig(env, sc, sys)
      .then((r) => { setRaw(r.raw); setParsed(r.parsed); setExists(r.exists); })
      .catch(() => setMsg('✗ 加载失败'))
      .finally(() => setLoading(false));
  }, []);

  // 系统切换 → 落到该系统的默认/首个环境（持久化 env 若仍属于该系统则保留）
  useEffect(() => {
    if (!system) return;
    const entry = systems.find((s) => s.name === system);
    const keep = entry?.envs?.includes(currentEnv);
    loadEnv(keep ? currentEnv : (entry?.envs?.[0] || currentEnv || 'sit'), scope, system);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [system, systems]);

  const save = async () => {
    setSaving(true);
    setMsg('');
    try {
      const r = await referenceApi.saveEnvConfig(raw, currentEnv, scope, system);
      setMsg(`✓ 已保存（${r.scope === 'shared' ? '共享通用' : `${r.system} 本系统`} env.${r.env}.yaml）`);
      setExists(true);
    } catch (e: unknown) {
      setMsg(`✗ ${e instanceof Error ? e.message : '保存失败'}`);
    } finally {
      setSaving(false);
    }
  };

  const p = parsed as Record<string, any>;
  const accounts = (p.accounts || {}) as Record<string, { ad?: string; emp_no?: string; type?: string }>;

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex items-center gap-2 mb-2 flex-shrink-0 flex-wrap">
        <span className="text-xs font-medium text-gray-300">🌐 环境配置（{system || '—'}）</span>
        {/* 配置层：通用（共享文件）vs 本系统 */}
        <div className="flex rounded border border-border overflow-hidden text-xs ml-auto">
          {(Object.keys(SCOPE_LABELS) as Scope[]).map((sc) => (
            <button key={sc} onClick={() => loadEnv(currentEnv, sc, system)}
              className={`px-2.5 py-1 ${scope === sc ? 'bg-info/20 text-info' : 'bg-surface-3 text-gray-400 hover:text-gray-200'}`}>
              {SCOPE_LABELS[sc].label}
            </button>
          ))}
        </div>
        <select value={currentEnv} onChange={(e) => loadEnv(e.target.value, scope, system)}
          className="bg-surface-3 border border-border rounded px-2 py-1 text-xs" title="切换环境（env.{env}.yaml）">
          {sysEnvs.map((n) => <option key={n} value={n}>{n}</option>)}
          {!sysEnvs.includes(currentEnv) && <option value={currentEnv}>{currentEnv}</option>}
          {scope === 'shared' && sharedEnvNames.filter((n) => !sysEnvs.includes(n) && n !== currentEnv)
            .map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        {isAdmin && (
          <button onClick={save} disabled={saving || loading}
            className="px-3 py-1 rounded text-xs bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30 disabled:opacity-50">
            💾 保存
          </button>
        )}
        {msg && <span className={`text-xs ${msg.startsWith('✓') ? 'text-pass' : 'text-fail'}`}>{msg}</span>}
      </div>
      <div className="text-[10px] text-gray-600 mb-2 flex-shrink-0">{SCOPE_LABELS[scope].hint(system)}</div>

      <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
        {!exists && (
          <div className="text-xs text-warn bg-warn/10 border border-warn/30 rounded px-3 py-2">
            ⚠️ 该配置层/环境文件不存在——{isAdmin ? '保存后创建' : '需管理员创建'}（引擎缺配置时相关执行会 SKIP；共享层缺失时仅用系统层）。
          </div>
        )}

        {/* YAML 原文编辑（Monaco，防 js-yaml 往返丢中文注释） */}
        <div className="h-72 border border-border rounded-lg overflow-hidden flex-shrink-0">
          {loading ? (
            <div className="h-full flex items-center justify-center text-gray-500 text-xs">加载中…</div>
          ) : (
            <Editor language="yaml" theme={tokens.monaco} value={raw}
              onChange={(v) => setRaw(v || '')}
              options={{ fontSize: 12, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false, readOnly: !isAdmin }} />
          )}
        </div>

        {/* 结构化预览 */}
        <div className="border border-border rounded-lg overflow-hidden flex-shrink-0">
          <div className="px-3 py-2 border-b border-border text-xs font-medium bg-surface-2">
            {SCOPE_LABELS[scope].label}预览（{scope === 'shared' ? '_shared' : system} · env.{currentEnv}）
          </div>
          <div className="p-3 space-y-3 text-xs text-gray-400">
            {scope === 'system' ? (
              <>
                <Section title="网关">
                  {Object.entries(p).filter(([k]) => k.endsWith('_base')).map(([k, v]) => (
                    <KV key={k} k={k} v={String(v || '')} />
                  ))}
                  {Object.keys(p).filter((k) => k.endsWith('_base')).length === 0 && <div className="text-gray-600">（未配置）</div>}
                </Section>
                <Section title="资源码">
                  <KV k="default_resource_code" v={String(p.default_resource_code || '')} />
                </Section>
                <Section title="账号池（accounts）">
                  {Object.entries(accounts).map(([alias, info]) => (
                    <KV key={alias} k={`accounts.${alias}`}
                      v={info.type === 'internal' ? 'internal token' : `${info.ad || ''} / ${info.emp_no || ''}`} />
                  ))}
                  {Object.keys(accounts).length === 0 && <div className="text-gray-600">（未配置）</div>}
                </Section>
                <Section title="可用环境">
                  <KV k="envs" v={sysEnvs.join(', ')} />
                  <KV k="账号别名" v={sysAccounts.join(', ')} />
                </Section>
              </>
            ) : (
              <>
                <Section title="SSO（集团身份）">
                  <KV k="sso.domain" v={String((p.sso as Record<string, string>)?.domain || '')} />
                  <KV k="sso.app_id" v={String((p.sso as Record<string, string>)?.app_id || '')} />
                </Section>
                <Section title="internal_token（服务凭证）">
                  <KV k="url" v={String((p.internal_token as Record<string, string>)?.url || '')} />
                  <KV k="client_id" v={String((p.internal_token as Record<string, string>)?.client_id || '')} />
                  <KV k="client_secret" v={(p.internal_token as Record<string, string>)?.client_secret ? '***' : '（回退环境变量 SG_*_CLIENT_SECRET）'} />
                  <KV k="scope" v={String((p.internal_token as Record<string, string>)?.scope || '')} />
                </Section>
                <div className="text-gray-600">共享层可放置任何跨系统复用的键；系统层同键会整体覆盖。</div>
              </>
            )}
            <div className="border-t border-border pt-2 text-[10px] text-gray-600">
              加载语义：共享打底 + 系统覆盖（顶层键合并）。数据库连接见下方「数据库」卡（物理存于本系统 env 的 db 段）。
            </div>
          </div>
        </div>

        {/* 数据库连接（系统专属，跟随栏1选中系统与当前 env） */}
        <DbCard system={system} env={currentEnv} isAdmin={isAdmin}
          envConflict={scope === 'system'}
          onSaved={() => { if (scope === 'system') loadEnv(currentEnv, scope, system); }} />
      </div>
    </div>
  );
}

// ── 数据库连接卡（自 Settings DbTab 迁入，system 不再写死）──

function DbCard({ system, env, isAdmin, envConflict, onSaved }: {
  system: string; env: string; isAdmin: boolean; envConflict: boolean; onSaved: () => void;
}) {
  const [dbForm, setDbForm] = useState({ host: '', port: 3306, user: '', password: '', name: '', charset: 'utf8mb4' });
  const [dbTestMsg, setDbTestMsg] = useState('');
  const [raw, setRaw] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!system) return;
    setDbTestMsg('');
    referenceApi.envConfig(env, 'system', system).then((r) => {
      setRaw(r.raw);
      const db = (r.parsed as Record<string, Record<string, unknown>>)?.db || {};
      setDbForm({
        host: String(db.host || ''), port: Number(db.port || 3306),
        user: String(db.user || ''), password: String(db.password || ''),
        name: String(db.name || ''), charset: String(db.charset || 'utf8mb4'),
      });
    }).catch(() => {});
  }, [env, system]);

  const updateDb = (key: string, value: string | number) => {
    const next = { ...dbForm, [key]: value };
    setDbForm(next);
    try {
      const lines = raw.split('\n'); const newLines: string[] = [];
      let inDb = false, dbWritten = false;
      for (const line of lines) {
        if (line.startsWith('db:')) { inDb = true; newLines.push('db:');
          newLines.push(`  host: "${next.host}"`, `  port: ${next.port}`, `  user: "${next.user}"`,
            `  password: "${next.password}"`, `  name: "${next.name}"`, `  charset: "${next.charset}"`);
          dbWritten = true; continue; }
        if (inDb && line.match(/^\s+\S/)) continue;
        if (inDb && !line.match(/^\s/)) inDb = false;
        newLines.push(line);
      }
      if (!dbWritten) { newLines.push('', 'db:',
        `  host: "${next.host}"`, `  port: ${next.port}`, `  user: "${next.user}"`,
        `  password: "${next.password}"`, `  name: "${next.name}"`, `  charset: "${next.charset}"`); }
      setRaw(newLines.join('\n'));
    } catch { /* ignore */ }
  };

  const save = async () => {
    setSaving(true);
    setDbTestMsg('');
    try {
      await referenceApi.saveEnvConfig(raw, env, 'system', system);
      setDbTestMsg('✓ 已保存（引擎只读校验连接，下次执行生效）');
      onSaved();
    } catch (e: unknown) {
      setDbTestMsg(`❌ ${e instanceof Error ? e.message : '保存失败'}`);
    } finally {
      setSaving(false);
    }
  };

  const testDb = async () => {
    setDbTestMsg('测试中…');
    try {
      const r = await referenceApi.testDb(env, system);
      setDbTestMsg(r.ok ? `✅ ${r.message}` : `❌ ${r.error}`);
    } catch (e: unknown) { setDbTestMsg(`❌ ${e instanceof Error ? e.message : '测试失败'}`); }
  };

  return (
    <div className="bg-surface-2 border border-border rounded-lg p-3 flex-shrink-0">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-gray-300">🗄 数据库连接（{system || '—'} · env.{env}）</span>
        {isAdmin && (
          <div className="flex items-center gap-2">
            <button onClick={save} disabled={saving || !system}
              className="text-[10px] px-2 py-1 rounded bg-pass/15 text-pass hover:bg-pass/25 disabled:opacity-50">💾 保存</button>
            <button onClick={testDb} disabled={!system}
              className="text-[10px] px-2 py-1 rounded bg-info/10 text-info hover:bg-info/20 disabled:opacity-50">🔌 测试连接</button>
            {dbTestMsg && <span className="text-[10px]">{dbTestMsg}</span>}
          </div>
        )}
      </div>
      <p className="text-[10px] text-gray-600 mb-2">
        SpecGuard 引擎只读校验连接（db_oracle 断言数据源），db 段物理存于 systems/{system || '{system}'}/config/env.{env}.yaml。
        {envConflict && isAdmin && <span className="text-warn"> 与上方 YAML 编辑同一文件——请先保存 YAML 再改库连接，避免互相覆盖。</span>}
      </p>
      {!system ? (
        <div className="text-center text-gray-600 text-xs py-3">先在栏1选择系统</div>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          <Field label="主机" value={dbForm.host} onChange={(v) => updateDb('host', v)} disabled={!isAdmin} />
          <Field label="端口" value={String(dbForm.port)} onChange={(v) => updateDb('port', Number(v) || 3306)} disabled={!isAdmin} />
          <Field label="用户名" value={dbForm.user} onChange={(v) => updateDb('user', v)} disabled={!isAdmin} />
          <Field label="密码" value={dbForm.password} onChange={(v) => updateDb('password', v)} type="password" disabled={!isAdmin} />
          <Field label="数据库" value={dbForm.name} onChange={(v) => updateDb('name', v)} disabled={!isAdmin} />
          <Field label="字符集" value={dbForm.charset} onChange={(v) => updateDb('charset', v)} disabled={!isAdmin} />
        </div>
      )}
    </div>
  );
}

// ── 通用小组件 ──

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-medium text-gray-300 mb-1">{title}</div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="text-gray-500 font-mono w-36 truncate flex-shrink-0">{k}</span>
      <span className="text-gray-300 truncate">{v || '—'}</span>
    </div>
  );
}

function Field({ label, value, onChange, type = 'text', placeholder = '', disabled = false }: {
  label: string; value: string; onChange: (v: string) => void; type?: string; placeholder?: string; disabled?: boolean;
}) {
  return (
    <div>
      <label className="block text-[10px] text-gray-500 mb-0.5">{label}</label>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} disabled={disabled}
        className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono placeholder-gray-600 disabled:opacity-50" />
    </div>
  );
}
