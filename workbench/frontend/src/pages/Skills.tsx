/** Skills — Skill 注册表管理页（T-080） */

import { useEffect, useState } from 'react';
import { skillsApi } from '../api';
import type { SkillItem } from '../api';

export default function Skills() {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<SkillItem | null>(null);

  useEffect(() => {
    skillsApi.list()
      .then(r => setSkills(r.skills))
      .catch(e => setError(e.message || '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="max-w-4xl">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-200">Skill 注册表</h2>
        <p className="text-fs-body text-gray-500 mt-1">
          Agent 技能清单（{skills.length} 个技能，仅只读查询）
        </p>
      </div>

      {error && (
        <div className="mb-3 px-3 py-2 rounded-lg text-sm bg-red-900/30 text-red-400 border border-red-700/50">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-center text-gray-500 text-sm py-12">加载中…</div>
      ) : (
        <div className="flex gap-4">
          {/* 技能列表 */}
          <div className="flex-1 space-y-2">
            {skills.map(s => (
              <button key={s.name} onClick={() => setSelected(s)}
                className={`w-full text-left px-3 py-2.5 rounded-lg border transition-colors ${
                  selected?.name === s.name
                    ? 'border-info/50 bg-info/10'
                    : 'border-border bg-surface-2 hover:bg-surface-3'
                }`}>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-200">{s.name}</span>
                  <span className="text-fs-aux text-gray-500 font-mono">v{s.version}</span>
                  {s.source && (
                    <span className="text-fs-aux px-1 py-0.5 rounded bg-surface-3 text-gray-500">{s.source}</span>
                  )}
                </div>
                <p className="text-fs-body text-gray-400 mt-0.5 line-clamp-2">{s.description}</p>
              </button>
            ))}
            {skills.length === 0 && (
              <div className="text-center text-gray-600 text-sm py-10">暂无技能</div>
            )}
          </div>

          {/* 详情面板 */}
          {selected && (
            <div className="w-72 flex-shrink-0 bg-surface-2 border border-border rounded-lg p-4 space-y-3">
              <div>
                <h3 className="text-sm font-bold text-gray-200">{selected.name}</h3>
                <p className="text-fs-body text-gray-500 mt-0.5">v{selected.version}</p>
              </div>
              <div className="text-fs-body text-gray-400 leading-relaxed">{selected.description}</div>
              {selected.author && (
                <div>
                  <span className="text-fs-aux text-gray-500">作者：</span>
                  <span className="text-fs-body text-gray-300">{selected.author}</span>
                </div>
              )}
              {selected.depends_tools && selected.depends_tools.length > 0 && (
                <div>
                  <span className="text-fs-aux text-gray-500 block mb-1">依赖工具：</span>
                  <div className="flex flex-wrap gap-1">
                    {selected.depends_tools.map(t => (
                      <span key={t} className="text-fs-aux px-1.5 py-0.5 rounded bg-info/10 text-info">{t}</span>
                    ))}
                  </div>
                </div>
              )}
              {selected.source && (
                <div>
                  <span className="text-fs-aux text-gray-500">来源：</span>
                  <span className="text-fs-body text-gray-400">{selected.source}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}