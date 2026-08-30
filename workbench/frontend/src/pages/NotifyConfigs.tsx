// 通知配置管理：钉钉/飞书 webhook 配置 + 测试发送（J-3）
// T-996：二合一后作为反哺闭环「通知配置」页签内嵌（embedded），
// 补 system/scenario_pattern 用例级过滤维度 + fail/drift/skip 事件。

import { useState, useEffect } from 'react';
import { notifyApi, type NotifyConfig } from '../api';

const CHANNEL_LABELS: Record<string, string> = {
  dingtalk: '钉钉',
  feishu: '飞书',
};

const EVENT_LABELS: Record<string, string> = {
  vulnerability: '漏洞',
  plan_failure: '任务失败',
  plan_success: '任务成功',
  fail: '场景失败',
  drift: '场景漂移',
  skip: '场景跳过',
};

// 用例级事件（订阅任一即展示 system/scenario_pattern 过滤字段）
const CASE_EVENTS = ['fail', 'drift', 'skip'];

export default function NotifyConfigs({ embedded = false }: { embedded?: boolean }) {
  const [configs, setConfigs] = useState<NotifyConfig[]>([]);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<NotifyConfig | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [testingId, setTestingId] = useState('');

  // 表单字段
  const [name, setName] = useState('');
  const [channel, setChannel] = useState('feishu');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [secret, setSecret] = useState('');
  const [mentionMobiles, setMentionMobiles] = useState('');
  const [events, setEvents] = useState<string[]>(['plan_failure', 'vulnerability']);
  const [enabled, setEnabled] = useState(true);
  const [system, setSystem] = useState('');
  const [pattern, setPattern] = useState('*');

  const load = async () => {
    try {
      const data = await notifyApi.list();
      setConfigs(data.configs);
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => { load(); }, []);

  const resetForm = () => {
    setName(''); setChannel('feishu'); setWebhookUrl(''); setSecret('');
    setMentionMobiles(''); setEvents(['plan_failure', 'vulnerability']); setEnabled(true);
    setSystem(''); setPattern('*');
    setEditing(null);
  };

  const openCreate = () => {
    resetForm();
    setShowForm(true);
  };

  const openEdit = (cfg: NotifyConfig) => {
    setName(cfg.name); setChannel(cfg.channel); setWebhookUrl(cfg.webhook_url);
    setSecret(''); setMentionMobiles(cfg.mention_mobiles);
    setEvents(cfg.events); setEnabled(cfg.enabled);
    setSystem(cfg.system || ''); setPattern(cfg.scenario_pattern || '*');
    setEditing(cfg);
    setShowForm(true);
  };

  const handleSubmit = async () => {
    if (!name) { setError('请输入配置名称'); return; }
    if (!webhookUrl) { setError('请输入 webhook URL'); return; }
    setSubmitting(true);
    setError(''); setSuccess('');
    try {
      const body = { name, channel, webhook_url: webhookUrl, secret: secret || undefined, mention_mobiles: mentionMobiles, events, enabled, system, scenario_pattern: pattern || '*' };
      if (editing) {
        await notifyApi.update(editing.id, body);
        setSuccess(`配置 ${name} 更新成功`);
      } else {
        await notifyApi.create(body);
        setSuccess(`配置 ${name} 创建成功`);
      }
      setShowForm(false);
      resetForm();
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (cfg: NotifyConfig) => {
    if (!confirm(`确定删除通知配置 ${cfg.name}？`)) return;
    try {
      await notifyApi.delete(cfg.id);
      setSuccess(`配置 ${cfg.name} 已删除`);
      load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleTest = async (cfg: NotifyConfig) => {
    setTestingId(cfg.id);
    setError(''); setSuccess('');
    try {
      const result = await notifyApi.test(cfg.id);
      if (result.ok) {
        setSuccess(`测试消息已发送到 ${cfg.name}`);
      } else {
        setError(`测试发送失败：${result.message}`);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setTestingId('');
    }
  };

  const toggleEvent = (event: string) => {
    setEvents(prev => prev.includes(event) ? prev.filter(e => e !== event) : [...prev, event]);
  };

  return (
    <div className={embedded ? 'flex flex-col' : 'flex flex-col h-full max-w-4xl'}>
      {!embedded && (
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-fs-title font-bold text-gray-200">🔔 通知配置</h2>
            <p className="text-fs-body text-gray-500 mt-1">配置钉钉/飞书群聊 webhook，接收漏洞和任务失败通知</p>
          </div>
          <button onClick={openCreate} className="px-3 py-1.5 bg-info text-white rounded text-fs-lead hover:bg-info/90">
            + 新建配置
          </button>
        </div>
      )}
      {embedded && (
        <div className="mb-3 flex justify-end">
          <button onClick={openCreate} className="px-3 py-1.5 bg-info text-white rounded text-fs-lead hover:bg-info/90">
            + 新建配置
          </button>
        </div>
      )}

      {error && <div className="bg-fail/12 border border-fail/35 rounded p-2 mb-3 text-fail text-fs-lead">{error}</div>}
      {success && <div className="bg-green-900/30 border border-green-700/50 rounded p-2 mb-3 text-green-400 text-fs-lead">{success}</div>}

      {/* 配置列表 */}
      <div className="mb-4">
        {configs.length === 0 ? (
          <div className="text-center text-gray-600 text-fs-lead py-8">暂无通知配置，点击「新建配置」添加</div>
        ) : (
          <div className="space-y-2">
            {configs.map(cfg => (
              <div key={cfg.id} className="flex items-center justify-between p-3 rounded-lg border border-border bg-surface-1">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-fs-lead text-gray-300 font-medium">{cfg.name}</span>
                    <span className="text-fs-body px-1.5 py-0.5 rounded bg-surface-3 text-gray-400">{CHANNEL_LABELS[cfg.channel] || cfg.channel}</span>
                    <span className={`text-fs-body px-1.5 py-0.5 rounded ${cfg.enabled ? 'bg-green-900/30 text-green-400' : 'bg-gray-700 text-gray-500'}`}>
                      {cfg.enabled ? '✅ 启用' : '⏸️ 禁用'}
                    </span>
                  </div>
                  <div className="text-fs-body text-gray-600 mt-1">
                    {cfg.events.map(e => EVENT_LABELS[e] || e).join(' · ')}
                    {cfg.mention_mobiles && <span className="ml-2">@{cfg.mention_mobiles}</span>}
                    {cfg.events.some(e => CASE_EVENTS.includes(e)) && (
                      <span className="ml-2 text-gray-700">范围: {cfg.system || '全部系统'} / {cfg.scenario_pattern || '*'}</span>
                    )}
                  </div>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => handleTest(cfg)} disabled={testingId === cfg.id}
                    className="px-2 py-1 text-fs-body bg-info/20 text-info rounded hover:bg-info/30 disabled:opacity-40">
                    {testingId === cfg.id ? '发送中...' : '测试'}
                  </button>
                  <button onClick={() => openEdit(cfg)} className="px-2 py-1 text-fs-body bg-surface-3 text-gray-400 rounded hover:bg-surface-2">编辑</button>
                  <button onClick={() => handleDelete(cfg)} className="px-2 py-1 text-fs-body bg-fail/12 text-fail rounded hover:bg-fail/12">删除</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 新建/编辑表单 */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowForm(false)}>
          <div className="bg-surface-1 rounded-lg border border-border p-4 w-full max-w-lg" onClick={e => e.stopPropagation()}>
            <h3 className="text-fs-lead font-bold text-gray-200 mb-3">{editing ? '编辑配置' : '新建通知配置'}</h3>

            <div className="space-y-3">
              <div>
                <label className="text-fs-body text-gray-500">配置名称</label>
                <input value={name} onChange={e => setName(e.target.value)} placeholder="如：TDM 研发群"
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-300" />
              </div>

              <div>
                <label className="text-fs-body text-gray-500">渠道</label>
                <div className="flex gap-2 mt-1">
                  <button onClick={() => setChannel('dingtalk')} className={`px-3 py-1.5 text-fs-body rounded ${channel === 'dingtalk' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>钉钉</button>
                  <button onClick={() => setChannel('feishu')} className={`px-3 py-1.5 text-fs-body rounded ${channel === 'feishu' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>飞书</button>
                </div>
              </div>

              <div>
                <label className="text-fs-body text-gray-500">Webhook URL</label>
                <input value={webhookUrl} onChange={e => setWebhookUrl(e.target.value)} placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-300" />
                {editing && <p className="text-fs-aux text-gray-600 mt-0.5">留空则不修改现有 URL</p>}
              </div>

              <div>
                <label className="text-fs-body text-gray-500">加签密钥{channel === 'feishu' ? '（飞书不需要）' : '（钉钉可选）'}</label>
                <input value={secret} onChange={e => setSecret(e.target.value)} placeholder={editing ? '留空不修改' : 'SEC...'}
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-300"
                  disabled={channel === 'feishu'} />
              </div>

              <div>
                <label className="text-fs-body text-gray-500">@ 手机号（可选，逗号分隔）</label>
                <input value={mentionMobiles} onChange={e => setMentionMobiles(e.target.value)} placeholder="13800138000,13900139000"
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-300" />
              </div>

              <div>
                <label className="text-fs-body text-gray-500">订阅事件</label>
                <div className="flex gap-2 mt-1 flex-wrap">
                  {Object.entries(EVENT_LABELS).map(([event, label]) => (
                    <button key={event} onClick={() => toggleEvent(event)}
                      className={`px-3 py-1.5 text-fs-body rounded ${events.includes(event) ? 'bg-info/20 text-info' : 'bg-surface-3 text-gray-500'}`}>
                      {events.includes(event) ? '✅ ' : ''}{label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 用例级过滤：订阅 fail/drift/skip 时生效 */}
              {events.some(e => CASE_EVENTS.includes(e)) && (
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-fs-body text-gray-500">系统过滤（空 = 全部）</label>
                    <input value={system} onChange={e => setSystem(e.target.value)} placeholder="tdm"
                      className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-300" />
                  </div>
                  <div>
                    <label className="text-fs-body text-gray-500">场景 pattern（fnmatch）</label>
                    <input value={pattern} onChange={e => setPattern(e.target.value)} placeholder="PP-*"
                      className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-lead text-gray-300" />
                  </div>
                </div>
              )}

              <div>
                <label className="text-fs-body text-gray-500">启用</label>
                <button onClick={() => setEnabled(!enabled)}
                  className={`ml-2 px-2 py-0.5 text-fs-body rounded ${enabled ? 'bg-green-900/30 text-green-400' : 'bg-gray-700 text-gray-500'}`}>
                  {enabled ? '✅ 启用' : '⏸️ 禁用'}
                </button>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-fs-lead bg-surface-3 text-gray-400 rounded hover:bg-surface-2">取消</button>
              <button onClick={handleSubmit} disabled={submitting}
                className="px-4 py-1.5 bg-info text-white rounded text-fs-lead hover:bg-info/90 disabled:opacity-40">
                {submitting ? '保存中...' : editing ? '保存' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
