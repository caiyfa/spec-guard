/** History — 历史运行对比 + 租约可视化 */
import { useEffect, useState } from 'react';
import { runsApi, type RunSummary } from '../api';

export default function History() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selA, setSelA] = useState<string>('');
  const [selB, setSelB] = useState<string>('');

  useEffect(() => {
    runsApi.history(20).then((r) => {
      setRuns(r);
      if (r.length >= 2) { setSelA(r[0].run_id); setSelB(r[1].run_id); }
    });
  }, []);

  const a = runs.find((r) => r.run_id === selA);
  const b = runs.find((r) => r.run_id === selB);

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">📈 历史对比</h2>

      {/* 选择器 */}
      <div className="flex gap-4 items-center text-sm">
        <label className="text-gray-400">
          当前：
          <select value={selA} onChange={(e) => setSelA(e.target.value)} className="ml-1 bg-surface-3 border border-border rounded px-2 py-1">
            {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
          </select>
        </label>
        <label className="text-gray-400">
          基线：
          <select value={selB} onChange={(e) => setSelB(e.target.value)} className="ml-1 bg-surface-3 border border-border rounded px-2 py-1">
            {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
          </select>
        </label>
      </div>

      {/* 对比统计 */}
      {a && b && (
        <div className="grid grid-cols-2 gap-4">
          {[{ label: '当前', data: a }, { label: '基线', data: b }].map(({ label, data }) => (
            <div key={label} className="bg-surface-2 border border-border rounded-lg p-4">
              <div className="text-xs text-gray-500 mb-2">{label}：{data.run_id} · {data.env}</div>
              <div className="flex gap-4 text-sm">
                <span className="text-pass">✓ {data.stats.pass}</span>
                <span className="text-fail">✗ {data.stats.fail}</span>
                <span className="text-skip">⊘ {data.stats.skip}</span>
                <span className="text-blocked">⊗ {data.stats.blocked}</span>
                <span className="text-gray-400">共 {data.stats.total}</span>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                通过率 {data.stats.total ? Math.round(data.stats.pass / data.stats.total * 100) : 0}%
                {data.stats.warnings > 0 && ` · ⚠️ ${data.stats.warnings} WARN`}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 租约可视化 */}
      {a && Object.keys(a.leases).length > 0 && (
        <div className="bg-surface-2 border border-border rounded-lg p-4">
          <div className="text-sm font-medium mb-3">🔗 资源租约快照（{a.run_id}）</div>
          <div className="space-y-2">
            {Object.entries(a.leases).map(([type, keys]) =>
              Object.entries(keys).map(([key, holder]) => (
                <div key={`${type}-${key}`} className="flex items-center gap-3">
                  <span className="text-xs font-mono text-gray-400 w-36">{type}: {key}</span>
                  <div className="flex-1 h-5 bg-surface-3 rounded relative overflow-hidden">
                    <div className="absolute inset-y-0.5 left-1 right-1/3 bg-info/60 rounded flex items-center px-2 text-[10px] text-white">
                      {holder}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
          <p className="text-[11px] text-gray-600 mt-2">session 级租约，进程结束即消亡</p>
        </div>
      )}

      {/* 运行列表 */}
      <div className="bg-surface-2 border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-border text-sm font-medium">运行历史</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="px-4 py-2">Run ID</th>
              <th className="px-4 py-2">环境</th>
              <th className="px-4 py-2">时间</th>
              <th className="px-4 py-2">通过</th>
              <th className="px-4 py-2">失败</th>
              <th className="px-4 py-2">通过率</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id} className="border-b border-border/50 hover:bg-surface-3">
                <td className="px-4 py-2 font-mono text-xs text-info">{r.run_id}</td>
                <td className="px-4 py-2 text-xs">{r.env}</td>
                <td className="px-4 py-2 text-xs text-gray-400">{r.started_at}</td>
                <td className="px-4 py-2 text-pass text-xs">{r.stats.pass}</td>
                <td className="px-4 py-2 text-fail text-xs">{r.stats.fail}</td>
                <td className="px-4 py-2 text-xs">
                  {r.stats.total ? Math.round(r.stats.pass / r.stats.total * 100) : 0}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
