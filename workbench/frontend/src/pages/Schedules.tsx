/** Schedules — 定时任务调度页面（I-3） */

import { useState, useEffect, useCallback } from 'react';
import { schedulesApi } from '../api';
import type { ScheduledJob } from '../api';

const CRON_PRESETS: { label: string; value: string }[] = [
  { label: '每小时', value: '0 * * * *' },
  { label: '每天 2:00', value: '0 2 * * *' },
  { label: '每天 8:00', value: '0 8 * * *' },
  { label: '每周一 8:00', value: '0 8 * * 1' },
  { label: '每月 1 日 8:00', value: '0 8 1 * *' },
  { label: '每 5 分钟', value: '*/5 * * * *' },
];

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  success: { text: '✅ 成功', color: 'text-pass' },
  failed: { text: '❌ 失败', color: 'text-fail' },
  partial: { text: '⚠️ 部分成功', color: 'text-warn' },
  error: { text: '❌ 错误', color: 'text-fail' },
  skipped_busy: { text: '⏭️ 跳过（执行忙）', color: 'text-gray-500' },  // T-302：T-117 互斥跳过状态
  '': { text: '—', color: 'text-gray-600' },
};

export default function Schedules() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [plans, setPlans] = useState<{ id: string; name: string; scenario_count: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editingJob, setEditingJob] = useState<ScheduledJob | null>(null);
  const [running, setRunning] = useState<string>('');

  // 表单状态
  const [formName, setFormName] = useState('');
  const [formPlanId, setFormPlanId] = useState('');
  const [formCron, setFormCron] = useState('0 2 * * *');
  const [formNotifyConfigId, setFormNotifyConfigId] = useState('');
  const [formEnabled, setFormEnabled] = useState(true);

  const loadJobs = useCallback(async () => {
    try {
      setLoading(true);
      const r = await schedulesApi.list();
      setJobs(r.jobs || []);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPlans = useCallback(async () => {
    try {
      const r = await schedulesApi.listPlans();
      setPlans(r.plans || []);
    } catch {
      // 静默处理
    }
  }, []);

  useEffect(() => {
    loadJobs();
    loadPlans();
  }, [loadJobs, loadPlans]);

  const handleCreate = () => {
    setEditingJob(null);
    setFormName('');
    setFormPlanId(plans[0]?.id || '');
    setFormCron('0 2 * * *');
    setFormNotifyConfigId('');
    setFormEnabled(true);
    setShowForm(true);
  };

  const handleEdit = (job: ScheduledJob) => {
    setEditingJob(job);
    setFormName(job.name);
    setFormPlanId(job.plan_id);
    setFormCron(job.cron);
    setFormNotifyConfigId(job.notify_config_id);
    setFormEnabled(job.enabled);
    setShowForm(true);
  };

  const handleSubmit = async () => {
    if (!formName.trim() || !formPlanId || !formCron.trim()) {
      setError('请填写完整：名称、计划、cron 表达式');
      return;
    }
    try {
      setError('');
      if (editingJob) {
        await schedulesApi.update(editingJob.id, {
          name: formName,
          plan_id: formPlanId,
          cron: formCron,
          notify_config_id: formNotifyConfigId,
          enabled: formEnabled,
        });
      } else {
        await schedulesApi.create({
          name: formName,
          plan_id: formPlanId,
          cron: formCron,
          notify_config_id: formNotifyConfigId,
          enabled: formEnabled,
        });
      }
      setShowForm(false);
      await loadJobs();
    } catch (e: any) {
      setError(e.message || '保存失败');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('确认删除此定时任务？')) return;
    try {
      await schedulesApi.delete(id);
      await loadJobs();
    } catch (e: any) {
      setError(e.message || '删除失败');
    }
  };

  const handleToggle = async (job: ScheduledJob) => {
    try {
      await schedulesApi.update(job.id, { enabled: !job.enabled });
      await loadJobs();
    } catch (e: any) {
      setError(e.message || '操作失败');
    }
  };

  const handleRun = async (id: string) => {
    try {
      setRunning(id);
      setError('');
      const result = await schedulesApi.run(id);
      alert(`执行完成：${result.status}\nRun ID: ${result.run_id}\n场景数: ${result.results?.length || 0}`);
      await loadJobs();
    } catch (e: any) {
      setError(e.message || '执行失败');
    } finally {
      setRunning('');
    }
  };

  return (
    <div className="p-6 max-w-6xl">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-fs-title font-semibold text-gray-200">定时任务调度</h1>
        <button
          onClick={handleCreate}
          className="px-3 py-1.5 bg-info text-white rounded text-fs-lead hover:bg-info/90 transition-colors"
        >
          + 新建任务
        </button>
      </div>

      {error && (
        <div className="mb-3 bg-fail/12 border border-fail/35 rounded p-2">
          <span className="text-fail text-fs-lead">❌ {error}</span>
        </div>
      )}

      {/* 任务列表 */}
      {loading ? (
        <div className="text-center text-gray-600 text-fs-lead py-8">加载中…</div>
      ) : jobs.length === 0 ? (
        <div className="text-center text-gray-600 text-fs-lead py-8">
          暂无定时任务，点击「新建任务」创建
        </div>
      ) : (
        <div className="bg-surface-2 rounded-lg overflow-hidden">
          <table className="w-full text-fs-lead">
            <thead>
              <tr className="border-b border-border text-gray-500 text-fs-body">
                <th className="px-3 py-2 text-left">名称</th>
                <th className="px-3 py-2 text-left">计划</th>
                <th className="px-3 py-2 text-left font-mono">Cron</th>
                <th className="px-3 py-2 text-left">状态</th>
                <th className="px-3 py-2 text-left">上次运行</th>
                <th className="px-3 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(job => {
                const plan = plans.find(p => p.id === job.plan_id);
                const statusInfo = STATUS_LABELS[job.last_run_status] || STATUS_LABELS[''];
                return (
                  <tr key={job.id} className="border-b border-border/50 hover:bg-surface-3/50">
                    <td className="px-3 py-2">
                      <div className="text-gray-300">{job.name}</div>
                      <div className="text-fs-aux text-gray-600 font-mono">{job.id}</div>
                    </td>
                    <td className="px-3 py-2 text-gray-400">
                      {plan ? plan.name : job.plan_id}
                      {plan && <span className="text-fs-aux text-gray-600 ml-1">({plan.scenario_count} 场景)</span>}
                    </td>
                    <td className="px-3 py-2 font-mono text-fs-body text-gray-400">{job.cron}</td>
                    <td className="px-3 py-2">
                      {job.enabled ? (
                        <span className="text-pass text-fs-body">✅ 启用</span>
                      ) : (
                        <span className="text-gray-500 text-fs-body">⏸️ 暂停</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className={`text-fs-body ${statusInfo.color}`}>{statusInfo.text}</div>
                      {job.last_run_at && (
                        <div className="text-fs-aux text-gray-600">{job.last_run_at}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right space-x-1">
                      <button
                        onClick={() => handleRun(job.id)}
                        disabled={running === job.id}
                        className="text-fs-body px-2 py-0.5 rounded bg-info/10 text-info hover:bg-info/20 disabled:opacity-40"
                        title="立即运行"
                      >
                        {running === job.id ? '⏳' : '▶️ 运行'}
                      </button>
                      <button
                        onClick={() => handleToggle(job)}
                        className="text-fs-body px-2 py-0.5 rounded bg-surface-3 text-gray-400 hover:text-gray-200"
                        title={job.enabled ? '暂停' : '启用'}
                      >
                        {job.enabled ? '⏸️' : '▶️'}
                      </button>
                      <button
                        onClick={() => handleEdit(job)}
                        className="text-fs-body px-2 py-0.5 rounded bg-surface-3 text-gray-400 hover:text-gray-200"
                      >
                        ✏️
                      </button>
                      <button
                        onClick={() => handleDelete(job.id)}
                        className="text-fs-body px-2 py-0.5 rounded bg-surface-3 text-fail/70 hover:text-fail"
                      >
                        🗑️
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 新建/编辑表单 */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-surface-1 rounded-lg p-6 w-96 max-w-[90vw]">
            <h2 className="text-fs-lead font-semibold text-gray-200 mb-4">
              {editingJob ? '编辑任务' : '新建定时任务'}
            </h2>

            <div className="space-y-3">
              {/* 任务名称 */}
              <div>
                <label className="text-fs-body text-gray-500 block mb-1">任务名称</label>
                <input
                  value={formName}
                  onChange={e => setFormName(e.target.value)}
                  placeholder="如：每日回归"
                  className="w-full bg-surface-2 border border-border rounded px-3 py-1.5 text-fs-lead text-gray-200"
                />
              </div>

              {/* 选择计划 */}
              <div>
                <label className="text-fs-body text-gray-500 block mb-1">测试计划</label>
                <select
                  value={formPlanId}
                  onChange={e => setFormPlanId(e.target.value)}
                  className="w-full bg-surface-2 border border-border rounded px-3 py-1.5 text-fs-lead text-gray-200"
                >
                  <option value="">— 选择计划 —</option>
                  {plans.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.scenario_count} 场景)
                    </option>
                  ))}
                </select>
                {plans.length === 0 && (
                  <span className="text-fs-aux text-gray-600">当前工作区暂无计划</span>
                )}
              </div>

              {/* Cron 预设 */}
              <div>
                <label className="text-fs-body text-gray-500 block mb-1">调度频率</label>
                <div className="flex gap-1 flex-wrap mb-1">
                  {CRON_PRESETS.map(preset => (
                    <button
                      key={preset.value}
                      onClick={() => setFormCron(preset.value)}
                      className={`text-fs-aux px-2 py-0.5 rounded border transition-colors ${
                        formCron === preset.value
                          ? 'bg-info/15 text-info border-info/30'
                          : 'bg-surface-2 text-gray-500 border-border hover:text-gray-300'
                      }`}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
                <input
                  value={formCron}
                  onChange={e => setFormCron(e.target.value)}
                  placeholder="0 2 * * *"
                  className="w-full bg-surface-2 border border-border rounded px-3 py-1.5 text-fs-lead text-gray-200 font-mono"
                />
                <span className="text-fs-aux text-gray-600">标准 5 字段 cron 表达式</span>
              </div>

              {/* 通知配置（可选） */}
              <div>
                <label className="text-fs-body text-gray-500 block mb-1">通知配置（可选）</label>
                <input
                  value={formNotifyConfigId}
                  onChange={e => setFormNotifyConfigId(e.target.value)}
                  placeholder="通知配置 ID（留空则通知所有订阅者）"
                  className="w-full bg-surface-2 border border-border rounded px-3 py-1.5 text-fs-lead text-gray-200"
                />
              </div>

              {/* 启用开关 */}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={formEnabled}
                  onChange={e => setFormEnabled(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-fs-body text-gray-400">创建后立即启用</span>
              </div>
            </div>

            {/* 按钮 */}
            <div className="flex gap-2 mt-5">
              <button
                onClick={handleSubmit}
                className="flex-1 px-3 py-1.5 bg-info text-white rounded text-fs-lead hover:bg-info/90"
              >
                {editingJob ? '保存' : '创建'}
              </button>
              <button
                onClick={() => setShowForm(false)}
                className="px-3 py-1.5 bg-surface-2 text-gray-400 rounded text-fs-lead hover:text-gray-200"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
