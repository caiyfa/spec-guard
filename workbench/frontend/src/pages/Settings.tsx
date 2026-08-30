/** Settings — 基础设置（SpecGuard 自身运行基础信息：模型配置 / 审计 / 执行参数 / Git）。
 *
 * 职责边界（T-308，T-1010 收窄）：
 * - 本页 = SpecGuard 运行所需：LLM 模型、审计开关、看门狗超时、Git 推送凭据
 * - 被测系统维度配置（系统包/工作区/环境 env/DB 校验连接）已并入「🧩 系统配置」页
 */
import { useEffect, useState, useCallback } from 'react';
import { modelApi, settingsApi } from '../api';
import type { ModelConfig } from '../api';

type Tab = 'models' | 'audit' | 'run' | 'git';

const TAB_LABELS: Record<Tab, string> = {
  models: '🧠 模型配置',
  audit: '🔍 审计',
  run: '▶ 执行',
  git: '🐙 Git 配置',
};

export default function Settings() {
  const [tab, setTab] = useState<Tab>('models');

  return (
    <div className="h-full flex flex-col">
      {/* 顶栏 */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">⚙️ 基础设置</h2>
        <span className="text-fs-aux text-gray-600">SpecGuard 运行基础信息 · 被测系统配置见「🧩 系统配置」</span>
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
        {tab === 'models' && <ModelsTab />}
        {tab === 'audit' && <AuditTab />}
        {tab === 'run' && <RunTab />}
        {tab === 'git' && <GitTab />}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════
// Tab 2: 模型配置（多模型管理）
// ══════════════════════════════════════════════════════════

type ModelForm = Omit<ModelConfig, 'id' | 'is_default' | 'created_at' | 'updated_at'> & { has_api_key: boolean };

// 上下文窗口经典档位：[label, 存储值]；空串 = 未设置（AgentChat 回退 DEFAULT_CTX_LIMIT=200k）
const CTX_OPTIONS: Array<[string, string]> = [
  ['未设置（默认 200k）', ''],
  ['200k', '200000'],
  ['400k', '400000'],
  ['1M', '1000000'],
];

// 最大输出档位：各模型典型最大输出满档 + 半档（如 1M 满档 + 512k 半档），合并去重；空串 = 不携带 max_tokens 跟随模型默认
const OUTPUT_OPTIONS: Array<[string, string]> = [
  ['未设置（跟随模型默认）', ''],
  ['4k', '4000'],
  ['8k', '8000'],
  ['16k', '16000'],
  ['32k', '32000'],
  ['64k', '64000'],
  ['128k', '128000'],
  ['512k', '512000'],
  ['1M', '1000000'],
];

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
          <span className="text-fs-aux text-gray-500">模型列表</span>
          <button onClick={handleAdd} className="text-fs-aux px-1.5 py-0.5 rounded bg-info/10 text-info hover:bg-info/20">+ 添加</button>
        </div>
        {models.map(m => (
          <button key={m.id} onClick={() => selectModel(m)}
            className={`w-full text-left px-2 py-1.5 rounded mb-1 transition-colors ${
              m.id === selectedId ? 'bg-info/10 text-info' : 'text-gray-400 hover:bg-surface-3'
            }`}>
            <div className="flex items-center gap-1">
              {m.is_default && <span className="text-yellow-500 text-fs-aux">★</span>}
              <span className="text-xs font-medium truncate">{m.name || '(未命名)'}</span>
            </div>
            <div className="text-fs-micro text-gray-600 font-mono truncate">{m.model || '(未配置)'}</div>
          </button>
        ))}
        {models.length === 0 && <p className="text-fs-aux text-gray-600 text-center py-4">暂无模型配置</p>}
      </div>

      {/* 右侧：编辑表单 */}
      <div className="flex-1 bg-surface-2 border border-border rounded-lg p-4 overflow-y-auto">
        {selectedId ? (
          <>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-gray-300">编辑模型：{editForm.name || '(未命名)'}</span>
              <div className="flex items-center gap-2">
                <button onClick={handleProbe} disabled={probing}
                  className="text-fs-aux px-2 py-1 rounded bg-info/10 text-info hover:bg-info/20 disabled:opacity-40">
                  {probing ? '探测中...' : '🔌 探测'}
                </button>
                <button onClick={handleSetDefault}
                  className="text-fs-aux px-2 py-1 rounded bg-yellow-600/20 text-yellow-400 hover:bg-yellow-600/30">
                  ★ 设为默认
                </button>
                <button onClick={handleDelete}
                  className="text-fs-aux px-2 py-1 rounded bg-red-900/20 text-red-400 hover:bg-red-900/30">
                  🗑 删除
                </button>
                <button onClick={handleSave}
                  className="text-fs-aux px-2 py-1 rounded bg-pass/10 text-pass hover:bg-pass/20">
                  💾 保存
                </button>
              </div>
            </div>
            {msg && <p className="text-fs-aux mb-2 text-gray-400">{msg}</p>}
            {probeMsg && <p className="text-fs-aux mb-2">{probeMsg}</p>}
            <div className="grid grid-cols-3 gap-3">
              <Field label="名称" value={editForm.name} onChange={(v) => setEditForm(p => ({ ...p, name: v }))} placeholder="DeepSeek-V4" />
              <Field label="Base URL" value={editForm.base_url} onChange={(v) => setEditForm(p => ({ ...p, base_url: v }))} placeholder="https://api.deepseek.com" />
              <Field label="API Key" value={editForm.api_key} onChange={(v) => setEditForm(p => ({ ...p, api_key: v }))} type="password" placeholder={editForm.has_api_key ? '已保存，留空则不修改' : 'sk-xxx'} />
              <Field label="Model" value={editForm.model} onChange={(v) => setEditForm(p => ({ ...p, model: v }))} placeholder="deepseek-v4-flash" />
              <Field label="Timeout (s)" value={editForm.timeout} onChange={(v) => setEditForm(p => ({ ...p, timeout: v }))} placeholder="120" />
              <SelectField label="上下文窗口" value={editForm.max_context_tokens} onChange={(v) => setEditForm(p => ({ ...p, max_context_tokens: v }))} options={CTX_OPTIONS} />
              <SelectField label="最大输出" value={editForm.max_output_tokens} onChange={(v) => setEditForm(p => ({ ...p, max_output_tokens: v }))} options={OUTPUT_OPTIONS} />
              {/* 思考开关 */}
              <div>
                <label className="block text-fs-aux text-gray-500 mb-0.5">启用思考</label>
                <select value={editForm.thinking_enabled}
                  onChange={(e) => setEditForm(p => ({ ...p, thinking_enabled: e.target.value }))}
                  className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono">
                  <option value="false">关闭</option>
                  <option value="true">开启</option>
                </select>
              </div>
              {/* 推理等级 */}
              <div>
                <label className="block text-fs-aux text-gray-500 mb-0.5">推理等级</label>
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
              <label className="block text-fs-aux text-gray-500 mb-0.5">请求体预览</label>
              <pre className="bg-surface-3 border border-border rounded px-2 py-1 text-fs-aux font-mono text-gray-400 overflow-x-auto">
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
        <div className="text-fs-aux text-gray-500 mt-2 space-y-1">
          <p>· 关闭（默认手动）：研发修正 spec 后需在 Agent 会话中或调用 POST /api/workspace/mark-audited 手动标记已审计，基线才复位。</p>
          <p>· 开启：Agent 写审计报告成功后自动更新基线，无需手动标记。</p>
        </div>
        {msg && <p className={`text-[11px] mt-2 ${msg.startsWith('✓') ? 'text-pass' : 'text-fail'}`}>{msg}</p>}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════
// Tab 5: Git 配置（多用户隔离，token 加密存储）
// ══════════════════════════════════════════════════════════

function GitTab() {
  const [gitName, setGitName] = useState('');
  const [gitEmail, setGitEmail] = useState('');
  const [gitToken, setGitToken] = useState('');
  const [hasToken, setHasToken] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    settingsApi.getGitConfig().then(r => {
      setGitName(r.name || '');
      setGitEmail(r.email || '');
      setHasToken(r.has_token || false);
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage('');
    try {
      const r = await settingsApi.saveGitConfig({
        name: gitName, email: gitEmail, token: gitToken,
      });
      setHasToken(r.has_token);
      setGitToken('');  // 清空密码输入框（已加密存储）
      setMessage(r.has_token ? '✅ 已保存，token 已加密存储' : '✅ 已保存');
    } catch (e: any) {
      setMessage(`❌ 保存失败: ${e.message || ''}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-2xl p-1">
      <div className="rounded-md border border-border bg-surface-3 p-4">
        <h3 className="text-sm font-medium text-gray-200 mb-1">🐙 Git 远端推送配置</h3>
        <p className="text-[11px] text-gray-500 mb-3">
          配置后，提交 delta 起草区后可以一键推送到远端仓库。
          参考：Gitee 设置 → 私人令牌 → 创建令牌（勾选 projects 写入权限）。
          token 使用 Fernet 加密存储（同模型 api_key 方案），仅用于推送不落地远程 URL。
        </p>
        <div className="space-y-2">
          <Field label="user.name" value={gitName} onChange={setGitName} placeholder="Zhang San" />
          <Field label="user.email" value={gitEmail} onChange={setGitEmail} placeholder="zhangsan@example.com" />
          <Field label="token (HTTPS PAT)" value={gitToken} onChange={setGitToken}
            placeholder={hasToken ? '已配置（不修改请留空）' : 'ghp_xxx...'} type="password" />
        </div>
        <div className="text-fs-aux text-gray-600 mt-1">
          {hasToken ? '✅ 已配置 token（重新输入可覆盖）' : '未配置 token——推送到远端需要 HTTPS PAT'}
        </div>
        <button onClick={handleSave} disabled={saving}
          className="mt-3 px-3 py-1.5 rounded text-xs bg-pass/20 text-pass border border-pass/30 hover:bg-pass/30">
          {saving ? '保存中…' : '💾 保存'}
        </button>
        {message && <p className={`text-[11px] mt-2 ${message.startsWith('✅') ? 'text-pass' : 'text-fail'}`}>{message}</p>}
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
      <label className="block text-fs-aux text-gray-500 mb-0.5">{label}</label>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono placeholder-gray-600" />
    </div>
  );
}

// 下拉档位选择（模型 token 参数用）
function SelectField({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: Array<[string, string]>;
}) {
  // 存量值兜底：已保存的旧值（如 1048576）不在档位中时追加「自定义」项——select 非命中值会白屏显示首项，不丢值不静默改
  const known = options.some(([, v]) => v === value);
  const items = known ? options : [...options, [`自定义: ${value}`, value]];
  return (
    <div>
      <label className="block text-fs-aux text-gray-500 mb-0.5">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-[11px] font-mono">
        {items.map(([l, v]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}


