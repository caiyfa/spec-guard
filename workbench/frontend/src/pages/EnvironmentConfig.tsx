/** EnvironmentConfig — 环境信息独立维护页（T-306/T-308/T-309）
 *
 * 职责：测试执行基础信息，按「配置层 × 环境」维护：
 * - 通用配置（systems/_shared/config/env.{env}.yaml）：跨系统复用（如集团 SSO）
 * - 系统配置（systems/{system}/config/env.{env}.yaml）：本系统专属（网关/账号池/资源码）
 * 加载语义：共享打底 + 系统覆盖（顶层键合并）。数据库连接在「系统设置 → 数据库」。
 */
import { useCallback, useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { referenceApi, type SystemInfo } from '../api';
import { useJsTokens } from '../theme';

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

type Scope = 'system' | 'shared';

const SCOPE_LABELS: Record<Scope, { label: string; hint: (sys: string) => string }> = {
  system: { label: '本系统配置', hint: (sys) => `systems/${sys}/config/env.{env}.yaml（网关/账号池/资源码，系统专属）` },
  shared: { label: '通用配置', hint: () => 'systems/_shared/config/env.{env}.yaml（跨系统复用，如集团 SSO）' },
};

export default function EnvironmentConfig() {
  const tokens = useJsTokens();
  const [systems, setSystems] = useState<SystemInfo[]>([]);
  const [currentSystem, setCurrentSystem] = useState('tdm');
  const [sharedEnvNames, setSharedEnvNames] = useState<string[]>([]);
  const [currentEnv, setCurrentEnv] = useState('sit');
  const [scope, setScope] = useState<Scope>('system');
  const [raw, setRaw] = useState('');
  const [parsed, setParsed] = useState<Record<string, unknown>>({});
  const [exists, setExists] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  // 当前系统的环境列表（来自全系统枚举）
  const sysEnvs = systems.find((s) => s.name === currentSystem)?.envs || [];
  const sysAccounts = systems.find((s) => s.name === currentSystem)?.accounts || [];

  // 系统列表 + 共享通用层（跨系统只有一份，与当前系统无关）
  useEffect(() => {
    referenceApi.envs().then((r) => {
      setSystems(r.systems);
      setSharedEnvNames(r.shared_envs.map((e) => e.name));
      setCurrentSystem((prev) => r.systems.some((s) => s.name === prev) ? prev : (r.systems[0]?.name || prev));
      setCurrentEnv(r.current);
    }).catch(() => {});
  }, []);

  // 切换环境/配置层/系统 → 加载配置
  const loadEnv = useCallback((env: string, sc: Scope, sys: string) => {
    setCurrentEnv(env);
    setScope(sc);
    setCurrentSystem(sys);
    setLoading(true);
    setMsg('');
    referenceApi.envConfig(env, sc, sys)
      .then((r) => { setRaw(r.raw); setParsed(r.parsed); setExists(r.exists); })
      .catch(() => setMsg('✗ 加载失败'))
      .finally(() => setLoading(false));
  }, []);

  // 切换系统 → 落到该系统的首个环境
  const switchSystem = (sys: string) => {
    const firstEnv = systems.find((s) => s.name === sys)?.envs?.[0] || 'sit';
    loadEnv(firstEnv, scope, sys);
  };

  // 初始加载（系统/环境/配置层任一变化时由显式调用触发，此处仅首次挂载）
  useEffect(() => { loadEnv(currentEnv, scope, currentSystem); }, [loadEnv]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setSaving(true);
    setMsg('');
    try {
      const r = await referenceApi.saveEnvConfig(raw, currentEnv, scope, currentSystem);
      setMsg(`✓ 已保存（${r.scope === 'shared' ? '共享通用' : `${r.system} 本系统`} env.${r.env}.yaml）`);
    } catch (e: unknown) {
      setMsg(`✗ ${e instanceof Error ? e.message : '保存失败'}`);
    } finally {
      setSaving(false);
    }
  };

  // 结构化预览（按配置层展示各自区块）
  const p = parsed as Record<string, any>;
  const accounts = (p.accounts || {}) as Record<string, { ad?: string; emp_no?: string; type?: string }>;

  return (
    <div className="h-full flex flex-col space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold">🌐 环境配置</h2>
        {/* 系统选择：被测系统适配包（systems/{system}/config/） */}
        <select
          value={currentSystem}
          onChange={(e) => switchSystem(e.target.value)}
          className="bg-surface-3 border border-border rounded px-2 py-1 text-xs"
          title="切换被测系统（systems/{system}/config/）">
          {systems.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
          {systems.length === 0 && <option value="tdm">tdm</option>}
        </select>
        {/* T-309：配置层切换——通用（共享文件）vs 本系统 */}
        <div className="flex rounded border border-border overflow-hidden text-xs">
          {(Object.keys(SCOPE_LABELS) as Scope[]).map((sc) => (
            <button key={sc} onClick={() => loadEnv(currentEnv, sc, currentSystem)}
              className={`px-2.5 py-1 ${scope === sc ? 'bg-info/20 text-info' : 'bg-surface-3 text-gray-400 hover:text-gray-200'}`}>
              {SCOPE_LABELS[sc].label}
            </button>
          ))}
        </div>
        <select
          value={currentEnv}
          onChange={(e) => loadEnv(e.target.value, scope, currentSystem)}
          className="bg-surface-3 border border-border rounded px-2 py-1 text-xs"
          title="切换环境（env.{env}.yaml）">
          {sysEnvs.map((n) => <option key={n} value={n}>{n}</option>)}
          {scope === 'shared' && sharedEnvNames.filter((n) => !sysEnvs.includes(n))
            .map((n) => <option key={n} value={n}>{n}</option>)}
          {sysEnvs.length === 0 && sharedEnvNames.length === 0 && <option value="sit">sit</option>}
        </select>
        <button onClick={save} disabled={saving}
          className="px-3 py-1 rounded text-xs bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30 disabled:opacity-50">
          💾 保存
        </button>
        {msg && <span className={`text-xs ${msg.startsWith('✓') ? 'text-pass' : 'text-fail'}`}>{msg}</span>}
        <span className="ml-auto text-[10px] text-gray-600">{SCOPE_LABELS[scope].hint(currentSystem)}</span>
      </div>

      {!exists && (
        <div className="text-xs text-warn bg-warn/10 border border-warn/30 rounded px-3 py-2">
          ⚠️ 该配置层/环境文件不存在——保存后创建（引擎缺配置时相关执行会 SKIP；共享层缺失时仅用系统层）。
        </div>
      )}

      <div className="flex-1 flex gap-3 min-h-0">
        {/* YAML 原文编辑（Monaco，防 js-yaml 往返丢中文注释） */}
        <div className="flex-1 border border-border rounded-lg overflow-hidden">
          {loading ? (
            <div className="h-full flex items-center justify-center text-gray-500">加载中…</div>
          ) : (
            <Editor language="yaml" theme={tokens.monaco} value={raw}
              onChange={(v) => setRaw(v || '')}
              options={{ fontSize: 13, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false }} />
          )}
        </div>

        {/* 结构化预览 */}
        <div className="w-[280px] flex-shrink-0 border border-border rounded-lg overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border text-xs font-medium bg-surface-2">
            {SCOPE_LABELS[scope].label}预览（{currentSystem} · env.{currentEnv}）
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3 text-xs text-gray-400">
            {scope === 'system' ? (
              <>
                <Section title="网关">
                  <KV k="tdm_base" v={String(p.tdm_base || '')} />
                  <KV k="hr_center_base" v={String(p.hr_center_base || '')} />
                  <KV k="oss_base" v={String(p.oss_base || '')} />
                  <KV k="oss_download_base" v={String(p.oss_download_base || '')} />
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
                <div className="text-gray-600">共享层可放置任何跨系统复用的键；系统层同键会覆盖。</div>
              </>
            )}
            <div className="border-t border-border pt-2 text-[10px] text-gray-600">
              加载语义：共享打底 + 系统覆盖（顶层键合并）。数据库连接维护入口：系统设置 → 数据库。
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
