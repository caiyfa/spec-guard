// AuditLog — 审计日志统一页（T-996 双审计统一）：
// 页签① MCP 调用审计（T-082）＋ 页签② 管理操作审计（原 AdminUsers 审计区，/users/audit-log）

import { useCallback, useEffect, useState } from 'react';
import { auditApi, usersApi, type AuditCall } from '../api';

const VERDICT_LABEL: Record<string, { label: string; color: string }> = {
  ok: { label: '通过', color: 'text-green-400' },
  'denied-whitelist': { label: '越权拒绝', color: 'text-red-400' },
  'denied-side-effect': { label: '副作用违规', color: 'text-red-400' },
  warn: { label: '警告', color: 'text-amber-400' },
};

function McpAudit() {
  const [calls, setCalls] = useState<AuditCall[]>([]);
  const [emp, setEmp] = useState('');
  const [tool, setTool] = useState('');
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);

  const LIMIT = 50;

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const r = await auditApi.list({ emp: emp || undefined, tool: tool || undefined, limit: LIMIT, offset });
      setCalls(r.calls);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [emp, tool, offset]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSearch = () => {
    setOffset(0);
    fetchData();
  };

  return (
    <div className="max-w-6xl">
      <h2 className="text-base font-bold mb-4">MCP 调用审计日志</h2>

      {/* 过滤栏 */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <input
          className="input-sm w-32"
          placeholder="工号"
          value={emp}
          onChange={e => setEmp(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
        />
        <input
          className="input-sm w-40"
          placeholder="工具名"
          value={tool}
          onChange={e => setTool(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
        />
        <button className="btn btn-sm btn-primary" onClick={handleSearch} disabled={loading}>
          {loading ? '查询中…' : '查询'}
        </button>
      </div>

      {error && <div className="text-red-400 text-sm mb-3">✗ {error}</div>}

      {/* 表格 */}
      <div className="overflow-x-auto">
        <table className="w-full text-fs-body">
          <thead>
            <tr className="text-gray-500 border-b border-border">
              <th className="text-left py-2 pr-2 w-36">时间</th>
              <th className="text-left py-2 pr-2 w-20">工号</th>
              <th className="text-left py-2 pr-2 w-36">工具</th>
              <th className="text-left py-2 pr-2 w-24">副作用</th>
              <th className="text-left py-2 pr-2 w-20">判定</th>
              <th className="text-left py-2 pr-2">参数摘要</th>
            </tr>
          </thead>
          <tbody>
            {calls.length === 0 && !loading && (
              <tr><td colSpan={6} className="text-gray-500 text-center py-8">暂无审计记录</td></tr>
            )}
            {calls.map(call => {
              const v = VERDICT_LABEL[call.verdict] || { label: call.verdict, color: 'text-gray-400' };
              const isExpanded = expanded === call.id;
              return (
                <tr key={call.id}
                  className="border-b border-border/50 hover:bg-surface-3/30 cursor-pointer"
                  onClick={() => setExpanded(isExpanded ? null : call.id)}
                >
                  <td className="py-1.5 pr-2 text-gray-400 whitespace-nowrap font-mono">{call.created_at}</td>
                  <td className="py-1.5 pr-2 text-gray-300">{call.emp_no || '—'}</td>
                  <td className="py-1.5 pr-2 text-gray-200 font-mono">{call.tool_name}</td>
                  <td className="py-1.5 pr-2 text-gray-400">{call.side_effect}</td>
                  <td className={`py-1.5 pr-2 font-medium ${v.color}`}>{v.label}</td>
                  <td className="py-1.5 pr-2 text-gray-400 truncate max-w-xs">{call.args_digest || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      <div className="flex items-center justify-between mt-4">
        <div className="text-fs-body text-gray-500">
          {calls.length > 0 && `显示第 ${offset + 1}–${offset + calls.length} 条`}
        </div>
        <div className="flex gap-2">
          <button
            className="btn btn-xs"
            disabled={offset <= 0 || loading}
            onClick={() => setOffset(o => Math.max(0, o - LIMIT))}
          >
            ← 上一页
          </button>
          <button
            className="btn btn-xs"
            disabled={calls.length < LIMIT || loading}
            onClick={() => setOffset(o => o + LIMIT)}
          >
            下一页 →
          </button>
        </div>
      </div>

      {/* 展开的详情 */}
      {expanded !== null && (() => {
        const call = calls.find(c => c.id === expanded);
        if (!call) return null;
        return (
          <div className="mt-4 p-3 bg-surface-3/50 rounded border border-border text-fs-body space-y-2">
            <div><span className="text-gray-500">会话 ID：</span><span className="text-gray-300 font-mono">{call.session_id || '—'}</span></div>
            <div><span className="text-gray-500">用途：</span><span className="text-gray-300">{call.purpose || '—'}</span></div>
            <div><span className="text-gray-500">工作区：</span><span className="text-gray-300">{call.workspace || '—'}</span></div>
            <div><span className="text-gray-500">参数摘要：</span><span className="text-gray-300 font-mono break-all">{call.args_digest || '—'}</span></div>
            <div><span className="text-gray-500">结果摘要：</span><span className="text-gray-300 font-mono break-all">{call.result_digest || '—'}</span></div>
          </div>
        );
      })()}
    </div>
  );
}
// ── 页签②：管理操作审计（用户/角色/菜单/授权变更，原 AdminUsers 审计区）──
function AdminAudit() {
  const [audit, setAudit] = useState<any[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    usersApi.auditLog(100).then(r => setAudit(r.entries)).catch(e => setError(e.message || '加载失败'));
  }, []);

  return (
    <div className="bg-surface-2 border border-border rounded-lg overflow-hidden">
      {error && <div className="text-red-400 text-sm p-3">✗ {error}</div>}
      <table className="w-full text-fs-body">
        <thead>
          <tr className="text-left text-gray-500 border-b border-border">
            <th className="px-3 py-2">时间</th>
            <th className="px-3 py-2">操作人</th>
            <th className="px-3 py-2">动作</th>
            <th className="px-3 py-2">对象</th>
            <th className="px-3 py-2">详情</th>
          </tr>
        </thead>
        <tbody>
          {audit.map((a, i) => (
            <tr key={i} className="border-b border-border/50 text-gray-400">
              <td className="px-3 py-1.5 font-mono">{a.created_at}</td>
              <td className="px-3 py-1.5">{a.emp_no}</td>
              <td className="px-3 py-1.5">{a.action}</td>
              <td className="px-3 py-1.5">{a.target}</td>
              <td className="px-3 py-1.5 truncate max-w-[16rem]">{a.detail}</td>
            </tr>
          ))}
          {audit.length === 0 && !error && (
            <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-600">暂无审计记录</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── T-996：双审计统一一页两 tab（?tab=admin 深链 + localStorage 记忆）──
const AUDIT_TABS = [
  { id: 'mcp', label: '🛠 MCP 调用' },
  { id: 'admin', label: '👤 管理操作' },
] as const;
type AuditTab = typeof AUDIT_TABS[number]['id'];

export default function AuditLog() {
  const [tab, setTab] = useState<AuditTab>(() => {
    const q = new URLSearchParams(window.location.search).get('tab');
    const saved = localStorage.getItem('sg_audit_tab');
    const valid = (v: string | null): v is AuditTab => AUDIT_TABS.some(t => t.id === v);
    if (valid(q)) return q;
    if (valid(saved)) return saved;
    return 'mcp';
  });
  useEffect(() => { localStorage.setItem('sg_audit_tab', tab); }, [tab]);

  return (
    <div className="max-w-6xl">
      <div className="flex gap-1 mb-4">
        {AUDIT_TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-sm rounded ${tab === t.id ? 'bg-info text-white' : 'bg-surface-3 text-gray-400 hover:text-gray-200'}`}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'mcp' && <McpAudit />}
      {tab === 'admin' && <AdminAudit />}
    </div>
  );
}
