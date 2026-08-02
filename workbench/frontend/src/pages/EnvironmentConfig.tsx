/** EnvironmentConfig — 环境信息独立维护页（T-306/T-308）
 *
 * 职责：测试执行基础信息——被测系统侧（网关/账号池/资源码/SSO），按环境（sit/uat）维护。
 * 边界（T-308）：数据库连接属 SpecGuard 引擎校验基础设施，维护入口在「系统设置 → 数据库」；
 * 本页 YAML 原文为 env.{env}.yaml 整文件（含 db 段），结构化预览不重复展示 DB。
 */
import { useCallback, useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { referenceApi, type EnvEntry } from '../api';
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

export default function EnvironmentConfig() {
  const tokens = useJsTokens();
  const [envs, setEnvs] = useState<EnvEntry[]>([]);
  const [currentEnv, setCurrentEnv] = useState('sit');
  const [raw, setRaw] = useState('');
  const [parsed, setParsed] = useState<Record<string, unknown>>({});
  const [exists, setExists] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  // 环境列表
  useEffect(() => {
    referenceApi.envs().then((r) => {
      setEnvs(r.envs);
      setCurrentEnv(r.current);
    }).catch(() => {});
  }, []);

  // 切换环境 → 加载配置
  const loadEnv = useCallback((env: string) => {
    setCurrentEnv(env);
    setLoading(true);
    setMsg('');
    referenceApi.envConfig(env)
      .then((r) => { setRaw(r.raw); setParsed(r.parsed); setExists(r.exists); })
      .catch(() => setMsg('✗ 加载失败'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadEnv(currentEnv); }, [loadEnv]);

  const save = async () => {
    setSaving(true);
    setMsg('');
    try {
      const r = await referenceApi.saveEnvConfig(raw, currentEnv);
      setMsg(`✓ 已保存（env.${r.env}.yaml）`);
    } catch (e: unknown) {
      setMsg(`✗ ${e instanceof Error ? e.message : '保存失败'}`);
    } finally {
      setSaving(false);
    }
  };

  // 结构化预览（测试执行基础信息：网关/账号池/资源码/SSO；DB 归系统设置，不在此重复）
  const p = parsed as Record<string, any>;
  const accounts = (p.accounts || {}) as Record<string, { ad?: string; emp_no?: string; type?: string }>;

  return (
    <div className="h-full flex flex-col space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold">🌐 环境配置</h2>
        <select
          value={currentEnv}
          onChange={(e) => loadEnv(e.target.value)}
          className="bg-surface-3 border border-border rounded px-2 py-1 text-xs"
          title="切换环境（systems/tdm/config/env.{env}.yaml）">
          {envs.map((e) => <option key={e.name} value={e.name}>{e.name}</option>)}
          {envs.length === 0 && <option value="sit">sit</option>}
        </select>
        <button onClick={save} disabled={saving}
          className="px-3 py-1 rounded text-xs bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30 disabled:opacity-50">
          💾 保存
        </button>
        {msg && <span className={`text-xs ${msg.startsWith('✓') ? 'text-pass' : 'text-fail'}`}>{msg}</span>}
        <span className="ml-auto text-[10px] text-gray-600">测试执行基础信息 · 数据库连接在「系统设置」维护</span>
      </div>

      {!exists && (
        <div className="text-xs text-warn bg-warn/10 border border-warn/30 rounded px-3 py-2">
          ⚠️ env.{currentEnv}.yaml 不存在——保存后创建（引擎缺该环境配置时相关执行会 SKIP）。
        </div>
      )}

      <div className="flex-1 flex gap-3 min-h-0">
        {/* YAML 原文编辑（Monaco，防 js-yaml 往返丢中文注释；整文件含 db 段） */}
        <div className="flex-1 border border-border rounded-lg overflow-hidden">
          {loading ? (
            <div className="h-full flex items-center justify-center text-gray-500">加载中…</div>
          ) : (
            <Editor language="yaml" theme={tokens.monaco} value={raw}
              onChange={(v) => setRaw(v || '')}
              options={{ fontSize: 13, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false }} />
          )}
        </div>

        {/* 结构化预览（被测系统执行信息） */}
        <div className="w-[280px] flex-shrink-0 border border-border rounded-lg overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border text-xs font-medium bg-surface-2">结构化预览（env.{currentEnv}）</div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3 text-xs text-gray-400">
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
            <Section title="SSO">
              <KV k="sso.domain" v={String((p.sso as Record<string, string>)?.domain || '')} />
              <KV k="sso.app_id" v={String((p.sso as Record<string, string>)?.app_id || '')} />
            </Section>
            <div className="border-t border-border pt-2 text-[10px] text-gray-600">
              编辑走 Monaco 原文（保中文注释）；保存即写盘 env.{currentEnv}.yaml，下次执行生效。
              <span className="text-gray-500"> 数据库连接（SpecGuard 校验数据源）维护入口：系统设置 → 数据库。</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
