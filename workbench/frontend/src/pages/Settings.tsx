/** Settings — 环境配置统一设置页面（DB 连接表单 + YAML 编辑器） */
import React, { useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { referenceApi } from '../api';

export default function Settings() {
  const [raw, setRaw] = useState('');
  const [saveMsg, setSaveMsg] = useState('');
  const [loading, setLoading] = useState(true);
  const [dbForm, setDbForm] = useState({ host: '', port: 3306, user: '', password: '', name: 'hr_center', charset: 'utf8mb4' });
  const [dbTestMsg, setDbTestMsg] = useState('');

  useEffect(() => {
    referenceApi.envConfig().then((r) => {
      setRaw(r.raw);
      // 从 YAML 解析 DB 配置到表单
      const db = (r.parsed as Record<string, Record<string, unknown>>)?.db || {};
      setDbForm({
        host: String(db.host || ''),
        port: Number(db.port || 3306),
        user: String(db.user || ''),
        password: String(db.password || ''),
        name: String(db.name || 'hr_center'),
        charset: String(db.charset || 'utf8mb4'),
      });
    }).catch(() => setRaw('# 加载失败'))
      .finally(() => setLoading(false));
  }, []);

  // DB 表单变更 → 同步更新 YAML
  const updateDb = (key: string, value: string | number) => {
    const next = { ...dbForm, [key]: value };
    setDbForm(next);
    // 用 js-yaml 更新 YAML 中的 db 段
    try {
      const lines = raw.split('\n');
      const newLines: string[] = [];
      let inDb = false;
      let dbWritten = false;
      for (const line of lines) {
        if (line.startsWith('db:')) {
          inDb = true;
          newLines.push('db:');
          newLines.push(`  host: "${next.host}"`);
          newLines.push(`  port: ${next.port}`);
          newLines.push(`  user: "${next.user}"`);
          newLines.push(`  password: "${next.password}"`);
          newLines.push(`  name: "${next.name}"`);
          newLines.push(`  charset: "${next.charset}"`);
          dbWritten = true;
          continue;
        }
        if (inDb && line.match(/^\s+\S/)) continue; // 跳过旧 db 段
        if (inDb && !line.match(/^\s/)) inDb = false;
        newLines.push(line);
      }
      if (!dbWritten) {
        newLines.push('', 'db:');
        newLines.push(`  host: "${next.host}"`);
        newLines.push(`  port: ${next.port}`);
        newLines.push(`  user: "${next.user}"`);
        newLines.push(`  password: "${next.password}"`);
        newLines.push(`  name: "${next.name}"`);
        newLines.push(`  charset: "${next.charset}"`);
      }
      setRaw(newLines.join('\n'));
    } catch { /* ignore */ }
  };

  const save = async () => {
    setSaveMsg('');
    try {
      await referenceApi.saveEnvConfig(raw);
      setSaveMsg('✓ 已保存（下次执行生效）');
    } catch (e: unknown) {
      setSaveMsg(`✗ ${e instanceof Error ? e.message : '保存失败'}`);
    }
  };

  const testDb = async () => {
    setDbTestMsg('测试中…');
    // 先保存再测试
    await referenceApi.saveEnvConfig(raw).catch(() => {});
    try {
      const r = await referenceApi.testDb();
      setDbTestMsg(r.ok ? `✅ ${r.message}` : `❌ ${r.error}`);
    } catch (e: unknown) {
      setDbTestMsg(`❌ ${e instanceof Error ? e.message : '测试失败'}`);
    }
  };

  const insertTemplate = (template: string) => {
    setRaw((prev) => prev + '\n' + template);
  };

  return (
    <div className="h-full flex flex-col space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">⚙️ 环境设置</h2>
        <button onClick={save}
          className="px-4 py-1.5 rounded-md text-sm font-medium bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30">
          💾 保存配置
        </button>
      </div>
      {saveMsg && (
        <p className={`text-sm ${saveMsg.startsWith('✓') ? 'text-pass' : 'text-fail'}`}>{saveMsg}</p>
      )}

      {/* 数据库连接表单 */}
      <div className="bg-surface-2 border border-border rounded-lg p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-gray-300">🗄 数据库连接</span>
          <div className="flex items-center gap-2">
            <button onClick={testDb}
              className="text-[10px] px-2 py-1 rounded bg-info/10 text-info hover:bg-info/20">
              🔌 测试连接
            </button>
            {dbTestMsg && <span className="text-[10px]">{dbTestMsg}</span>}
          </div>
        </div>
        <div className="grid grid-cols-6 gap-2">
          <DbField label="主机" value={dbForm.host} onChange={(v) => updateDb('host', v)} />
          <DbField label="端口" value={String(dbForm.port)} onChange={(v) => updateDb('port', Number(v) || 3306)} />
          <DbField label="用户名" value={dbForm.user} onChange={(v) => updateDb('user', v)} />
          <DbField label="密码" value={dbForm.password} onChange={(v) => updateDb('password', v)} type="password" />
          <DbField label="数据库" value={dbForm.name} onChange={(v) => updateDb('name', v)} />
          <DbField label="字符集" value={dbForm.charset} onChange={(v) => updateDb('charset', v)} />
        </div>
      </div>

      <div className="flex-1 flex gap-3 min-h-0">
        {/* YAML 编辑器 */}
        <div className="flex-1 border border-border rounded-lg overflow-hidden">
          {loading ? (
            <div className="h-full flex items-center justify-center text-gray-500">加载中…</div>
          ) : (
            <Editor language="yaml" theme="vs-dark" value={raw}
              onChange={(v) => setRaw(v || '')}
              options={{ fontSize: 13, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false }} />
          )}
        </div>

        {/* 参考面板 */}
        <div className="w-[280px] flex-shrink-0 border border-border rounded-lg overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border text-xs font-medium bg-surface-2">配置说明</div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3 text-xs text-gray-400">
            <Section title="网关地址">
              <KV k="tdm_base" v="TDM 业务网关" />
              <KV k="hr_center_base" v="权限中台（权限预言）" />
              <KV k="oss_base" v="OSS 附件服务" />
            </Section>
            <Section title="资源码">
              <KV k="default_resource_code" v="权限资源码（⚠️ UAT/生产必须改）" />
            </Section>
            <Section title="账号池">
              <KV k="accounts.default" v="主测试账号（TDM_ADMIN）" />
              <KV k="accounts.no_access" v="fail-secure 场景专用" />
              <KV k="accounts.restricted" v="受限账号（待配置）" />
            </Section>
            <Section title="数据库">
              <KV k="db.host" v="MySQL 主机（只读账号）" />
              <KV k="db.name" v="数据库名（hr_center）" />
            </Section>
            <Section title="SSO">
              <KV k="sso.domain" v="Authing SSO 域名" />
              <KV k="sso.app_id" v="应用 ID" />
            </Section>

            <div className="border-t border-border pt-3 mt-3">
              <div className="text-[11px] font-medium text-gray-300 mb-2">快速插入</div>
              <button onClick={() => insertTemplate('\n# 受限账号（取消注释填入真实值）\n# restricted: {ad: "TODO_AD", emp_no: "TODO_EMPNO"}')}
                className="w-full text-left text-[11px] px-2 py-1.5 rounded bg-surface-3 text-gray-400 hover:text-info hover:bg-info/10 mb-1">
                + restricted 账号模板
              </button>
              <button onClick={() => insertTemplate('\ncheck_version_header: false')}
                className="w-full text-left text-[11px] px-2 py-1.5 rounded bg-surface-3 text-gray-400 hover:text-info hover:bg-info/10">
                + check_version_header
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function DbField({ label, value, onChange, type = 'text' }: {
  label: string; value: string; onChange: (v: string) => void; type?: string;
}) {
  return (
    <div>
      <label className="block text-[10px] text-gray-500 mb-0.5">{label}</label>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono" />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-medium text-gray-300 mb-1">{title}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between">
      <span className="font-mono text-info/70">{k}</span>
      <span className="text-gray-500 text-right">{v}</span>
    </div>
  );
}
