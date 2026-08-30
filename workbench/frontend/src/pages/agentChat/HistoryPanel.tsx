import { useCallback, useEffect, useState } from 'react';
import { settingsApi, specApi, workspaceApi } from '../../api';
import type { GitLogResponse } from '../../api';
import { RebasePanel } from './RebasePanel';

// Field 通用输入组件（从 Settings.tsx 复用，AgentChat 未定义）
function Field({ label, value, onChange, type = 'text', placeholder = '' }: {
  label: string; value: string; onChange: (v: string) => void; type?: string; placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-fs-aux text-gray-500 mb-0.5">{label}</label>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-fs-body font-mono placeholder-gray-600" />
    </div>
  );
}

// 📜 提交历史——未推送提交列表 + 一键推送（分支级，不依赖 delta_id）
export function HistoryPanel({ onError }: { onError: (msg: string) => void }) {
  const [data, setData] = useState<GitLogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [pushing, setPushing] = useState(false);
  const [pushResult, setPushResult] = useState<{ ok: boolean; msg: string } | null>(null);
  // token 弹窗（未配置时推送触发补全）
  const [hasToken, setHasToken] = useState<boolean | null>(null);
  const [showTokenDialog, setShowTokenDialog] = useState(false);
  const [dlgName, setDlgName] = useState('');
  const [dlgEmail, setDlgEmail] = useState('');
  const [dlgToken, setDlgToken] = useState('');
  const [saving, setSaving] = useState(false);
  const [dlgError, setDlgError] = useState('');

  const load = useCallback(() => {
    setLoading(true);
    workspaceApi.gitLog(50)
      .then(r => setData(r))
      .catch((e: any) => onError(e.message || '加载提交历史失败'))
      .finally(() => setLoading(false));
    settingsApi.getGitConfig()
      .then(r => {
        setHasToken(r.has_token);
        setDlgName(r.name || '');
        setDlgEmail(r.email || '');
      })
      .catch(() => setHasToken(false));
  }, [onError]);

  useEffect(() => { load(); }, [load]);

  // 未推送提交：后端 git_log 直接返回（@{u}..HEAD 差集，分叉状态下可靠）
  const unpushed = data?.unpushed || [];
  const ahead = data?.ahead || 0;
  const behind = data?.behind || 0;
  const rebaseInProgress = data?.rebase_in_progress || false;

  const doPush = async () => {
    setPushing(true);
    setPushResult(null);
    try {
      const r = await specApi.pushBranch();
      setPushResult({ ok: r.ok, msg: r.note || r.error || (r.ok ? '推送成功' : '推送失败') });
      if (r.ok) load();  // 推送成功后刷新列表
    } catch (e: any) {
      setPushResult({ ok: false, msg: e.message || '推送异常' });
    } finally {
      setPushing(false);
    }
  };

  const handlePushClick = () => {
    if (hasToken) {
      doPush();
    } else {
      setShowTokenDialog(true);
      setDlgError('');
    }
  };

  const handleTokenSave = async () => {
    if (!dlgName.trim()) { setDlgError('user.name 必填'); return; }
    if (!dlgEmail.trim()) { setDlgError('user.email 必填'); return; }
    if (!dlgToken.trim()) { setDlgError('token 必填'); return; }
    setSaving(true);
    setDlgError('');
    try {
      await settingsApi.saveGitConfig({ name: dlgName, email: dlgEmail, token: dlgToken });
      setHasToken(true);
      setShowTokenDialog(false);
      doPush();  // 保存后直接推送
    } catch (e: any) {
      setDlgError(e.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="text-fs-body text-gray-600 text-center py-8">加载中…</div>;
  if (!data) return <div className="text-fs-body text-gray-600 text-center py-8">加载失败</div>;

  return (
    <div className="px-2 py-2 space-y-2">
      {/* 分支状态行 */}
      <div className="px-1 text-fs-body font-medium text-gray-300">
        📜 提交历史（{data.branch}）
        {data.synced ? (
          <span className="ml-1.5 text-fs-aux text-pass">✅ 已全部同步</span>
        ) : (
          <span className="ml-1.5 text-fs-aux text-warn">
            {ahead > 0 ? `⬆ ${ahead} 待推送` : ''}
            {behind > 0 ? ` · ⬇ ${behind} 待拉取（推送前自动 rebase）` : ''}
          </span>
        )}
      </div>

      {/* rebase 中断恢复面板（检测/冲突解决/完成或放弃，界面化操作） */}
      {rebaseInProgress && <RebasePanel onChanged={load} />}

      {/* 未推送提交列表 */}
      {unpushed.length === 0 ? (
        <div className="text-fs-body text-gray-600 text-center py-6">
          {data.synced ? '本地与远端完全同步' : '无未推送提交'}
        </div>
      ) : (
        <>
          {unpushed.map(c => (
            <div key={c.sha} className="rounded-lg border border-border bg-surface-2/70 p-2">
              <div className="flex items-center gap-1.5 cursor-pointer"
                onClick={() => setExpanded(prev => ({ ...prev, [c.sha]: !prev[c.sha] }))}>
                <span className="text-fs-aux font-mono text-info">{c.short_sha}</span>
                <span className="text-fs-body text-gray-200 truncate flex-1" title={c.message}>{c.message}</span>
                <span className="text-fs-micro text-gray-600 flex-shrink-0">{expanded[c.sha] ? '▲' : '▼'}</span>
              </div>
              <div className="text-fs-aux text-gray-600 mt-0.5">
                {c.author} · {c.date.slice(0, 16).replace('T', ' ')}
              </div>
              {expanded[c.sha] && (
                <div className="mt-1.5 space-y-0.5">
                  {c.files.map((f, i) => (
                    <div key={i} className="text-fs-aux font-mono text-gray-500 flex items-center gap-1">
                      <span className={
                        f.status === 'A' ? 'text-pass' : f.status === 'D' ? 'text-fail' : 'text-warn'
                      }>{f.status}</span>
                      <span className="truncate">{f.path}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {/* 推送按钮 */}
          <button onClick={handlePushClick} disabled={pushing || rebaseInProgress}
            className="w-full px-3 py-2 rounded bg-info text-white text-fs-lead hover:bg-info/90 disabled:opacity-40">
            {pushing ? '推送中…' : rebaseInProgress ? '🚫 rebase 中断中，请先处理冲突' : `🚀 推送 ${unpushed.length} 个提交到远端`}
          </button>
        </>
      )}

      {pushResult && (
        <div className={`text-fs-aux rounded px-1.5 py-1 ${pushResult.ok ? 'bg-pass/12 text-pass' : 'bg-fail/12 text-fail'}`}>
          {pushResult.ok ? '✅ ' : '❌ '}{pushResult.msg}
        </div>
      )}

      {/* 补 token 弹窗 */}
      {showTokenDialog && (
        <div className="fixed inset-0 z-50 bg-overlay/60 flex items-center justify-center"
          onClick={() => !saving && setShowTokenDialog(false)}>
          <div className="bg-surface-2 border border-border rounded-xl p-4 w-[440px] max-w-[92vw] shadow-2xl"
            onClick={e => e.stopPropagation()}>
            <div className="text-fs-lead font-medium text-gray-200 mb-2">🐙 配置 Git 推送 token</div>
            <p className="text-fs-body text-gray-500 mb-2 leading-relaxed">
              首次推送需要配置 HTTPS Personal Access Token。参考：Gitee 设置 → 私人令牌 → 创建令牌（勾选 projects 写入权限）。
              token 加密存储，仅用于推送远端。commit 时使用 user.name / user.email 作为提交身份。
            </p>
            <div className="space-y-2 mb-2">
              <Field label="user.name *" value={dlgName} onChange={setDlgName} placeholder="Zhang San" />
              <Field label="user.email *" value={dlgEmail} onChange={setDlgEmail} placeholder="zhangsan@example.com" />
              <Field label="token (HTTPS PAT) *" value={dlgToken} onChange={setDlgToken}
                placeholder="ghp_xxx..." type="password" />
            </div>
            {dlgError && <div className="text-fs-body text-fail mb-2">❌ {dlgError}</div>}
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowTokenDialog(false)} disabled={saving}
                className="px-3 py-1.5 rounded bg-surface-3 text-gray-300 text-fs-lead disabled:opacity-40">取消</button>
              <button onClick={handleTokenSave} disabled={saving}
                className="px-3 py-1.5 rounded bg-info text-white text-fs-lead disabled:opacity-40">
                {saving ? '保存并推送…' : '保存并推送'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
