/** Settings — 系统设置（SpecGuard 自身运行基础信息：数据库连接 / 模型配置 / 审计 / 执行参数）。
 *
 * 职责边界（T-308）：
 * - 本页 = SpecGuard 运行所需：DB 校验连接（引擎只读断言数据源）、LLM 模型、审计开关、看门狗超时
 * - 环境设置（🌐 环境配置页）= 测试执行基础信息：被测系统网关/账号池/资源码/SSO，按环境（sit/uat）维护
 * - 环境信息（YAML/SSO 预览）入口已迁移至「环境配置」页，本页不再重复
 */
import { useEffect, useState, useCallback } from 'react';
import { referenceApi, modelApi, settingsApi } from '../api';
import type { ModelConfig } from '../api';

type Tab = 'db' | 'models' | 'audit' | 'run';

const TAB_LABELS: Record<Tab, string> = {
  db: '🗄 数据库',
  models: '🧠 模型配置',
  audit: '🔍 审计',
  run: '▶ 执行',
};

export default function Settings() {
  const [tab, setTab] = useState<Tab>('models');

  return (
    <div className="h-full flex flex-col">
      {/* 顶栏 */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">⚙️ 系统设置</h2>
        <span className="text-[10px] text-gray-600">SpecGuard 运行基础信息 · 被测系统环境信息见「🌐 环境配置」</span>
      </div>

      {/* Tab 栏 */}
      <div className="flex gap-1 mb-3 border-b border-border">
        {(Object.keys(TAB_LABELS) as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t ? 'border-info text-info' : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}>
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      <div className="flex-1 overflow-y-auto">
        {tab === 'db' && <DbTab />}
        {tab === 'models' && <ModelsTab />}
        {tab === 'audit' && <AuditTab />}
        {tab === 'run' && <RunTab />}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════
// Tab 1: 数据库连接
// ══════════════════════════════════════════════════════════

function DbTab() {
  const [dbForm, setDbForm] = useState({ host: '', port: 3306, user: '', password: '', name: 'hr_center', charset: 'utf8mb4' });
  const [dbTestMsg, setDbTestMsg] = useState('');
  const [env, setEnv] = useState('sit');
  const [raw, setRaw] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    referenceApi.envConfig(env).then((r) => {
      setRaw(r.raw);
      const db = (r.parsed as Record<string, Record<string, unknown>>)?.db || {};
      setDbForm({
        host: String(db.host || ''), port: Number(db.port || 3306),
        user: String(db.user || ''), password: String(db.password || ''),
        name: String(db.name || 'hr_center'), charset: String(db.charset || 'utf8mb4'),
      });
    }).catch(() => {});
  }, [env]);

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
      await referenceApi.saveEnvConfig(raw, env);
      setDbTestMsg('✓ 已保存（引擎只读校验连接，下次执行生效）');
    } catch (e: unknown) {
      setDbTestMsg(`❌ ${e instanceof Error ? e.message : '保存失败'}`);
    } finally {
      setSaving(false);
    }
  };

  const testDb = async () => {
    setDbTestMsg('测试中…');
    try {
      const r = await referenceApi.testDb(env);
      setDbTestMsg(r.ok ? `✅ ${r.message}` : `❌ ${r.error}`);
    } catch (e: unknown) { setDbTestMsg(`❌ ${e instanceof Error ? e.message : '测试失败'}`); }
  };

  return (
    <div className="bg-surface-2 border border-border rounded-lg p-4 max-w-2xl">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-gray-300">数据库连接配置</span>
        <div className="flex items-center gap-2">
          <select value={env} onChange={(e) => setEnv(e.target.value)}
            className="bg-surface-3 border border-border rounded px-1.5 py-0.5 text-[10px]"
            title="按环境维护（env.{env}.yaml 的 db 段）">
            <option value="sit">sit</option>
            <option value="uat">uat</option>
          </select>
          <button onClick={save} disabled={saving}
            className="text-[10px] px-2 py-1 rounded bg-pass/15 text-pass hover:bg-pass/25 disabled:opacity-50">💾 保存</button>
          <button onClick={testDb} className="text-[10px] px-2 py-1 rounded bg-info/10 text-info hover:bg-info/20">🔌 测试连接</button>
          {dbTestMsg && <span className="text-[10px]">{dbTestMsg}</span>}
        </div>
      </div>
      <p className="text-[10px] text-gray-600 mb-3">
        SpecGuard 引擎只读校验连接（db_oracle 断言数据源）——属系统设置；
        被测系统业务信息（网关/账号/资源码/SSO）在「🌐 环境配置」页维护。db 段物理存于 env.{env}.yaml。
      </p>
      <div className="grid grid-cols-3 gap-3">
        <Field label="主机" value={dbForm.host} onChange={(v) => updateDb('host', v)} />
        <Field label="端口" value={String(dbForm.port)} onChange={(v) => updateDb('port', Number(v) || 3306)} />
        <Field label="用户名" value={dbForm.user} onChange={(v) => updateDb('user', v)} />
        <Field label="密码" value={dbForm.password} onChange={(v) => updateDb('password', v)} type="password" />
        <Field label="数据库" value={dbForm.name} onChange={(v) => updateDb('name', v)} />
        <Field label="字符集" value={dbForm.charset} onChange={(v) => updateDb('charset', v)} />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════
// Tab 2: 模型配置（多模型管理）
// ══════════════════════════════════════════════════════════

type ModelForm = Omit<ModelConfig, 'id' | 'is_default' | 'created_at' | 'updated_at'> & { has_api_key: boolean };

const EMPTY_MODEL: ModelForm = {
  name: '', base_url: '', api_key: '', model: '', timeout: '120',
  max_context_tokens: '', max_output_tokens: '', thinking_enabled: 'false', reasoning_effort: '',
  has_api_key: false,
};

function ModelsTab() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [editForm, setEditForm] = useState<ModelForm>({ ...EMPTY_MODEL });
  const [msg, setMsg] = useState('');
  const [probing, setProbing] = useState(false);
  const [probeMsg, setProbeMsg] = useState('');

  const loadModels = useCallback(async () => {
    try {
      const r = await modelApi.list();
      setModels(r.models || []);
      if (r.models.length > 0 && !selectedId) {
        const def = r.models.find(m => m.is_default) || r.models[0];
        setSelectedId(def.id);
        setEditForm(_toForm(def));
      }
    } catch { setModels([]); }
  }, [selectedId]);

  useEffect(() => { loadModels(); }, [loadModels]);

  const selectModel = (m: ModelConfig) => {
    setSelectedId(m.id);
    setEditForm(_toForm(m));
    setMsg(''); setProbeMsg('');
  };

  const handleAdd = async () => {
    try {
      const m = await modelApi.create({ ...EMPTY_MODEL, name: '新模型' });
      setModels(prev => [...prev, m]);
      selectModel(m);
      setMsg('✓ 已创建新模型');
    } catch (e: any) { setMsg(`✗ ${e.message}`); }
  };

  const handleSave = async () => {
    if (!selectedId) return;
    try {
      await modelApi.update(selectedId, editForm);
      await loadModels(); // 响应含明文 key，不回写前端 state，重新拉取脱敏列表
      setMsg('✓ 已保存');
    } catch (e: any) { setMsg(`✗ ${e.message}`); }
  };

  const handleDelete = async () => {
    if (!selectedId) return;
    try {
      await modelApi.delete(selectedId);
      setModels(prev => prev.filter(x => x.id !== selectedId));
      if (models.length > 1) selectModel(models.find(x => x.id !== selectedId)!);
      else { setSelectedId(''); setEditForm({ ...EMPTY_MODEL }); }
      setMsg('✓ 已删除');
    } catch (e: any) { setMsg(`✗ ${e.message}`); }
  };

  const handleSetDefault = async () => {
    if (!selectedId) return;
    try {
      await modelApi.setDefault(selectedId);
      setModels(prev => prev.map(x => ({ ...x, is_default: x.id === selectedId })));
      setMsg('✓ 已设为默认');
    } catch (e: any) { setMsg(`✗ ${e.message}`); }
  };

  const handleProbe = async () => {
    if (!selectedId) return;
    setProbing(true); setProbeMsg('');
    try {
      // 发送表单当前值，允许保存前测试
      const r = await modelApi.probe(selectedId, {
        base_url: editForm.base_url,
        api_key: editForm.api_key,
        model: editForm.model,
      });
      setProbeMsg(r.ok ? `✅ ${r.message}` : `❌ ${r.message}`);
    } catch (e: any) { setProbeMsg(`❌ ${e.message}`); }
    finally { setProbing(false); }
  };

  return (
    <div className="flex gap-4 h-full">
      {/* 左侧：模型列表 */}
      <div className="w-56 flex-shrink-0 bg-surface-2 border border-border rounded-lg p-2 overflow-y-auto">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] text-gray-500">模型列表</span>
          <button onClick={handleAdd} className="text-[10px] px-1.5 py-0.5 rounded bg-info/10 text-info hover:bg-info/20">+ 添加</button>
        </div>
        {models.map(m => (
          <button key={m.id} onClick={() => selectModel(m)}
            className={`w-full text-left px-2 py-1.5 rounded mb-1 transition-colors ${
              m.id === selectedId ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
            }`}>
            <div className="flex items-center gap-1">
              {m.is_default && <span className="text-yellow-500 text-[10px]">★</span>}
              <span className="text-xs font-medium truncate">{m.name || '(未命名)'}</span>
            </div>
            <div className="text-[9px] text-gray-600 font-mono truncate">{m.model || '(未配置)'}</div>
          </button>
        ))}
        {models.length === 0 && <p className="text-[10px] text-gray-600 text-center py-4">暂无模型配置</p>}
      </div>

      {/* 右侧：编辑表单 */}
      <div className="flex-1 bg-surface-2 border border-border rounded-lg p-4 overflow-y-auto">
        {selectedId ? (
          <>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-gray-300">编辑模型：{editForm.name || '(未命名)'}</span>
              <div className="flex items-center gap-2">
                <button onClick={handleProbe} disabled={probing}
                  className="text-[10px] px-2 py-1 rounded bg-info/10 text-info hover:bg-info/20 disabled:opacity-40">
                  {probing ? '探测中...' : '🔌 探测'}
                </button>
                <button onClick={handleSetDefault}
                  className="text-[10px] px-2 py-1 rounded bg-yellow-600/20 text-yellow-400 hover:bg-yellow-600/30">
                  ★ 设为默认
                </button>
                <button onClick={handleDelete}
                  className="text-[10px] px-2 py-1 rounded bg-red-900/20 text-red-400 hover:bg-red-900/30">
                  🗑 删除
                </button>
                <button onClick={handleSave}
                  className="text-[10px] px-2 py-1 rounded bg-pass/10 text-pass hover:bg-pass/20">
                  💾 保存
                </button>
              </div>
            </div>
            {msg && <p className="text-[10px] mb-2 text-gray-400">{msg}</p>}
            {probeMsg && <p className="text-[10px] mb-2">{probeMsg}</p>}
            <div className="grid grid-cols-3 gap-3">
              <Field label="名称" value={editForm.name} onChange={(v) => setEditForm(p => ({ ...p, name: v }))} placeholder="DeepSeek-V4" />
              <Field label="Base URL" value={editForm.base_url} onChange={(v) => setEditForm(p => ({ ...p, base_url: v }))} placeholder="https://api.deepseek.com" />
              <Field label="API Key" value={editForm.api_key} onChange={(v) => setEditForm(p => ({ ...p, api_key: v }))} type="password" placeholder={editForm.has_api_key ? '已保存，留空则不修改' : 'sk-xxx'} />
              <Field label="Model" value={editForm.model} onChange={(v) => setEditForm(p => ({ ...p, model: v }))} placeholder="deepseek-v4-flash" />
              <Field label="Timeout (s)" value={editForm.timeout} onChange={(v) => setEditForm(p => ({ ...p, timeout: v }))} placeholder="120" />
              <Field label="上下文窗口" value={editForm.max_context_tokens} onChange={(v) => setEditForm(p => ({ ...p, max_context_tokens: v }))} placeholder="1048576" />
              <Field label="最大输出" value={editForm.max_output_tokens} onChange={(v) => setEditForm(p => ({ ...p, max_output_tokens: v }))} placeholder="262144" />
              {/* 思考开关 */}
              <div>
                <label className="block text-[10px] text-gray-500 mb-0.5">启用思考</label>
                <select value={editForm.thinking_enabled}
                  onChange={(e) => setEditForm(p => ({ ...p, thinking_enabled: e.target.value }))}
                  className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono">
                  <option value="false">关闭</option>
                  <option value="true">开启</option>
                </select>
              </div>
              {/* 推理等级 */}
              <div>
                <label className="block text-[10px] text-gray-500 mb-0.5">推理等级</label>
                <select value={editForm.reasoning_effort}
                  onChange={(e) => setEditForm(p => ({ ...p, reasoning_effort: e.target.value }))}
                  disabled={editForm.thinking_enabled !== 'true'}
                  className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono disabled:opacity-40">
                  <option value="">默认</option>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                  <option value="max">max</option>
                </select>
              </div>
            </div>
            {/* 请求体预览 */}
            <div className="mt-3 pt-2 border-t border-border/50">
              <label className="block text-[10px] text-gray-500 mb-0.5">请求体预览</label>
              <pre className="bg-surface-3 border border-border rounded px-2 py-1 text-[10px] font-mono text-gray-400 overflow-x-auto">
{JSON.stringify({
  model: editForm.model || 'gpt-4o',
  ...(Number(editForm.max_output_tokens) > 0 ? { max_tokens: Number(editForm.max_output_tokens) } : {}),
  ...(editForm.thinking_enabled === 'true' ? {
    thinking: { type: 'enabled' },
    ...(editForm.reasoning_effort ? { reasoning_effort: editForm.reasoning_effort } : {}),
  } : {}),
}, null, 2)}
              </pre>
            </div>
          </>
        ) : (
          <div className="text-center text-gray-600 text-sm py-12">选择左侧模型或点击「+ 添加」创建新模型</div>
        )}
      </div>
    </div>
  );
}

function _toForm(m: ModelConfig): ModelForm {
  return {
    name: m.name, base_url: m.base_url, api_key: '', model: m.model,
    timeout: m.timeout,
    max_context_tokens: m.max_context_tokens, max_output_tokens: m.max_output_tokens,
    thinking_enabled: m.thinking_enabled, reasoning_effort: m.reasoning_effort,
    has_api_key: !!m.has_api_key,
  };
}

// ══════════════════════════════════════════════════════════
// Tab 6: 执行（T-204 看门狗超时配置）
// ══════════════════════════════════════════════════════════

function RunTab() {
  const [timeoutSec, setTimeoutSec] = useState(0);
  const [source, setSource] = useState('env');
  const [msg, setMsg] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    settingsApi.getRunTimeout()
      .then((r) => { setTimeoutSec(r.timeout_sec); setSource(r.source); })
      .catch(() => setMsg('✗ 加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    setMsg('');
    try {
      const r = await settingsApi.setRunTimeout(timeoutSec);
      setTimeoutSec(r.timeout_sec);
      setSource('settings');
      setMsg('✓ 已保存（后续触发的执行生效，无需重启）');
    } catch (e: unknown) {
      setMsg(`✗ ${e instanceof Error ? e.message : '保存失败'}`);
    }
  };

  return (
    <div className="max-w-2xl p-1">
      <div className="rounded-md border border-border bg-surface-3 p-4">
        <h3 className="text-sm font-medium text-gray-200 mb-1">执行看门狗超时（T-118）</h3>
        <p className="text-[11px] text-gray-500 mb-3">
          单次执行超过该时长（从触发起算）自动强制终止并标记 timeout——进程挂死不再永久占用执行队列。
          <span className="text-gray-600"> 0 = 禁用。</span>
          {source === 'env' && <span className="text-warn"> 当前由环境变量 SG_RUN_TIMEOUT 控制，保存后以设置值为准。</span>}
        </p>
        <div className="flex items-center gap-2">
          <input
            type="number" min={0} step={60}
            value={timeoutSec}
            disabled={loading}
            onChange={(e) => setTimeoutSec(Number(e.target.value) || 0)}
            className="w-32 bg-surface-3 border border-border rounded px-2 py-1.5 text-sm text-gray-200"
            placeholder="0 = 禁用"
          />
          <span className="text-xs text-gray-500">秒</span>
          <button onClick={save}
            className="px-3 py-1.5 rounded text-xs bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30">
            💾 保存
          </button>
          {msg && <span className={`text-xs ${msg.startsWith('✓') ? 'text-pass' : 'text-fail'}`}>{msg}</span>}
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════
// Tab 5: 审计（K-007 spec 签名基线更新方式）
// ══════════════════════════════════════════════════════════

function AuditTab() {
  const [autoUpdate, setAutoUpdate] = useState(false);
  const [msg, setMsg] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    settingsApi.getAuditBaseline()
      .then((r) => setAutoUpdate(r.auto_update))
      .catch(() => setMsg('✗ 加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const save = async (val: boolean) => {
    setAutoUpdate(val);
    setMsg('');
    try {
      await settingsApi.setAuditBaseline(val);
      setMsg('✓ 已保存');
    } catch (e: unknown) {
      setAutoUpdate(!val); // 失败回滚
      setMsg(`✗ ${e instanceof Error ? e.message : '保存失败'}`);
    }
  };

  return (
    <div className="max-w-2xl p-1">
      <div className="rounded-md border border-border bg-surface-3 p-4">
        <h3 className="text-sm font-medium text-gray-200 mb-1">Spec 签名基线更新方式</h3>
        <p className="text-[11px] text-gray-500 mb-3">
          路由通过对比 spec 文件签名与基线检测变更，决定「研发修正场景包文件后是否自动进入审计模式」（K-007）。
        </p>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={autoUpdate}
            disabled={loading}
            onChange={(e) => save(e.target.checked)}
          />
          <span className="text-sm text-gray-200">审计完成后自动更新基线</span>
        </label>
        <div className="text-[10px] text-gray-500 mt-2 space-y-1">
          <p>· 关闭（默认手动）：研发修正 spec 后需在 Agent 会话中或调用 POST /api/workspace/mark-audited 手动标记已审计，基线才复位。</p>
          <p>· 开启：Agent 写审计报告成功后自动更新基线，无需手动标记。</p>
        </div>
        {msg && <p className={`text-[11px] mt-2 ${msg.startsWith('✓') ? 'text-pass' : 'text-fail'}`}>{msg}</p>}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════
// 通用组件
// ══════════════════════════════════════════════════════════

function Field({ label, value, onChange, type = 'text', placeholder = '' }: {
  label: string; value: string; onChange: (v: string) => void; type?: string; placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-[10px] text-gray-500 mb-0.5">{label}</label>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono placeholder-gray-600" />
    </div>
  );
}


