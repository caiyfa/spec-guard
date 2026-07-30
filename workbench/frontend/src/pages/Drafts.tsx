// 草稿区三道闸（D1）：评审 → 格式校验 → 发布门禁 → 入库 / 废弃

import { useCallback, useEffect, useState } from 'react';
import { draftsApi } from '../api';
import type { DraftItem, ValidateReport } from '../api';

export default function Drafts() {
  const [drafts, setDrafts] = useState<DraftItem[]>([]);
  const [modules, setModules] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [content, setContent] = useState<string>('');
  const [report, setReport] = useState<ValidateReport | null>(null);
  const [targetModule, setTargetModule] = useState<string>('');
  const [customModule, setCustomModule] = useState('');  // K-017: 「新建模块…」手动输入
  const [busy, setBusy] = useState<'validate' | 'promote' | 'discard' | ''>('');
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [d, m] = await Promise.all([draftsApi.list(), draftsApi.modules()]);
      setDrafts(d.drafts);
      setModules(m.modules);
      if (!targetModule && m.modules.length > 0) setTargetModule(m.modules[0]);
    } catch (e: any) {
      setError(e.message || '加载失败');
    }
  }, [targetModule]);

  useEffect(() => { refresh(); }, [refresh]);

  const handleSelect = async (filename: string) => {
    setSelected(filename);
    setReport(null);
    setMessage(null);
    setError('');
    try {
      const r = await draftsApi.read(filename);
      setContent(r.content);
    } catch (e: any) {
      setError(e.message || '读取草稿失败');
      setContent('');
    }
  };

  const handleValidate = async () => {
    if (!selected) return;
    setBusy('validate');
    setMessage(null);
    try {
      const r = await draftsApi.validate(selected);
      setReport(r);
    } catch (e: any) {
      setError(e.message || '校验失败');
    } finally {
      setBusy('');
    }
  };

  const handlePromote = async () => {
    if (!selected) return;
    // K-017：模块目录后端自动创建；「新建模块…」选项时使用手动输入的路径
    const effectiveModule = targetModule === '__new__' ? customModule.trim() : targetModule;
    if (!effectiveModule) {
      setMessage({ ok: false, text: '❌ 请选择入库模块，或选择「新建模块…」输入新模块路径' });
      return;
    }
    if (!window.confirm(`确认将 ${selected} 入库到 scenarios/${effectiveModule}/？\n将依次执行：格式校验 → 更新契约基线 → 发布门禁（失败自动回滚）`)) return;
    setBusy('promote');
    setMessage(null);
    try {
      const r = await draftsApi.promote(selected, effectiveModule);
      setMessage({ ok: true, text: `✅ 入库成功：${r.target}${r.gate?.skipped ? '（门禁已跳过）' : '（发布门禁 PASS）'}` });
      setSelected('');
      setContent('');
      setReport(null);
      await refresh();
    } catch (e: any) {
      setMessage({ ok: false, text: `❌ 入库失败：${e.message}` });
    } finally {
      setBusy('');
    }
  };

  const handleDiscard = async () => {
    if (!selected) return;
    if (!window.confirm(`确认废弃 ${selected}？（移入 drafts/_trash/，可人工恢复）`)) return;
    setBusy('discard');
    setMessage(null);
    try {
      await draftsApi.discard(selected);
      setMessage({ ok: true, text: `已废弃：${selected}` });
      setSelected('');
      setContent('');
      setReport(null);
      await refresh();
    } catch (e: any) {
      setMessage({ ok: false, text: `❌ 废弃失败：${e.message}` });
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="flex gap-4 h-full">
      {/* 左：草稿列表 */}
      <div className="w-80 flex-shrink-0 flex flex-col">
        <div className="mb-3">
          <h2 className="text-lg font-bold text-gray-200">📝 草稿评审</h2>
          <p className="text-xs text-gray-500 mt-1">
            Agent 产物三道闸：人工评审 doc 层 → 格式校验 → 发布门禁，缺一不入库。
          </p>
        </div>
        <div className="flex-1 overflow-y-auto space-y-1.5">
          {drafts.length === 0 && (
            <div className="text-center text-gray-600 text-sm py-10">草稿区为空</div>
          )}
          {drafts.map(d => (
            <button
              key={d.filename}
              onClick={() => handleSelect(d.filename)}
              className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
                selected === d.filename
                  ? 'border-info bg-info/10'
                  : 'border-border bg-surface-2 hover:bg-surface-3'
              }`}
            >
              <div className="text-sm text-gray-200 font-mono">
                {d.scenario_id || d.filename}
                {d.stale && (
                  <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-yellow-900/40 text-yellow-400 font-normal"
                    title={`来源信息包（${d.source_meta}）存在已变更/已删除文件，草稿内容可能过时`}>
                    ⚠️ 信息包已变更
                  </span>
                )}
              </div>
              <div className="text-xs text-gray-500 truncate">{d.title || d.filename}</div>
              <div className="text-[10px] text-gray-600 mt-0.5">
                {d.modified}{d.author ? ` · ${d.author}` : ''}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 右：内容与操作 */}
      <div className="flex-1 flex flex-col min-w-0">
        {message && (
          <div className={`mb-3 px-3 py-2 rounded-lg text-sm ${
            message.ok ? 'bg-green-900/30 text-green-400 border border-green-700/50'
                       : 'bg-red-900/30 text-red-400 border border-red-700/50'
          }`}>{message.text}</div>
        )}
        {error && (
          <div className="mb-3 px-3 py-2 rounded-lg text-sm bg-red-900/30 text-red-400 border border-red-700/50">
            ❌ {error}
          </div>
        )}

        {!selected ? (
          <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">
            选择左侧草稿开始评审
          </div>
        ) : (
          <>
            {/* 操作栏 */}
            <div className="flex items-center gap-2 mb-3">
              <button
                onClick={handleValidate}
                disabled={busy !== ''}
                className="px-3 py-1.5 bg-surface-3 text-gray-200 rounded text-sm hover:bg-surface-2 disabled:opacity-40"
              >
                {busy === 'validate' ? '校验中…' : '① 格式校验'}
              </button>
              <select
                value={targetModule}
                onChange={e => setTargetModule(e.target.value)}
                className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300"
              >
                {modules.length === 0 && <option value="">（无已有模块）</option>}
                {modules.map(m => <option key={m} value={m}>{m}</option>)}
                <option value="__new__">＋ 新建模块…</option>
              </select>
              {targetModule === '__new__' && (
                <input
                  value={customModule}
                  onChange={e => setCustomModule(e.target.value)}
                  placeholder="新模块路径（如 system-settings/tag-library）"
                  className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300 w-56"
                />
              )}
              <button
                onClick={handlePromote}
                disabled={busy !== '' || (report !== null && report.verdict !== 'PASS')}
                title={report !== null && report.verdict !== 'PASS' ? '格式校验未通过，禁止入库' : ''}
                className="px-3 py-1.5 bg-info text-white rounded text-sm hover:bg-info/90 disabled:opacity-40"
              >
                {busy === 'promote' ? '入库中…' : '② 评审通过 · 入库'}
              </button>
              <button
                onClick={handleDiscard}
                disabled={busy !== ''}
                className="px-3 py-1.5 bg-red-900/40 text-red-400 rounded text-sm hover:bg-red-900/60 disabled:opacity-40"
              >
                废弃
              </button>
            </div>

            {/* 校验报告 */}
            {report && (
              <div className={`mb-3 px-3 py-2 rounded-lg border text-sm ${
                report.verdict === 'PASS' ? 'border-green-700/50 bg-green-900/20' : 'border-red-700/50 bg-red-900/20'
              }`}>
                <div className={report.verdict === 'PASS' ? 'text-green-400' : 'text-red-400'}>
                  {report.verdict === 'PASS' ? '✓ 格式校验通过' : '✗ 格式校验未通过'}
                  {report.summary && `（ERROR ${report.summary.error} / WARN ${report.summary.warn}）`}
                </div>
                {report.findings.length > 0 && (
                  <ul className="mt-1.5 space-y-1">
                    {report.findings.map((f, i) => (
                      <li key={i} className={`text-xs ${f.level === 'ERROR' ? 'text-red-400' : 'text-yellow-500'}`}>
                        [{f.level}/{f.rule}] {f.message}{f.hint ? `（${f.hint}）` : ''}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* YAML 内容 */}
            <pre className="flex-1 overflow-auto bg-surface-1 border border-border rounded-lg p-3 text-xs text-gray-300 font-mono whitespace-pre-wrap">
              {content}
            </pre>
          </>
        )}
      </div>
    </div>
  );
}
