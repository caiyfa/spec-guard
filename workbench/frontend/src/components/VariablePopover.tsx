/** VariablePopover — 变量角标弹窗
 *
 * 在输入框旁放一个小的 {x} 角标，点击弹出浮层展示可用变量库。
 * 选中变量后自动插入到对应输入框。
 */
import { useState, useRef, useEffect } from 'react';
import type { UpstreamVar } from '../api';

export interface LocalVar {
  saveName: string;
  stepType: string;
}

interface Props {
  localVars: LocalVar[];
  upstreamVars: UpstreamVar[];
  envVars: { path: string; desc: string; example: string }[];
  onInsert: (text: string) => void;
}

export default function VariablePopover({ localVars, upstreamVars, envVars, onInsert }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 点击外部关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as HTMLElement)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const pick = (path: string) => {
    onInsert(`{{${path}}}`);
    setOpen(false);
  };

  const sections: { title: string; icon: string; items: { path: string; label: string }[] }[] = [];

  // 当前场景变量
  if (localVars.length) {
    const items: { path: string; label: string }[] = [];
    localVars.forEach((v) => {
      items.push({ path: v.saveName, label: v.saveName });
      if (v.stepType === 'select_emp') items.push(
        { path: `${v.saveName}.no`, label: '工号' },
        { path: `${v.saveName}.activity_id`, label: '活动ID' },
        { path: `${v.saveName}.session_id`, label: '会话ID' },
      );
      if (v.stepType === 'call') items.push(
        { path: `${v.saveName}.status`, label: 'HTTP状态' },
        { path: `${v.saveName}.json`, label: '响应JSON' },
      );
      if (v.stepType === 'oss_upload') items.push(
        { path: `${v.saveName}.ossKey`, label: 'OSS key' },
        { path: `${v.saveName}.fileName`, label: '文件名' },
      );
      if (v.stepType === 'oss_download') items.push(
        { path: `${v.saveName}.file_path`, label: '本地路径' },
        { path: `${v.saveName}.file_size`, label: '文件大小' },
      );
    });
    sections.push({ title: '当前场景', icon: '📦', items });
  }

  // 上游变量
  upstreamVars.forEach((u) => {
    sections.push({
      title: `上游: ${u.scenario_id}`, icon: '🔗',
      items: u.saves.map((s) => ({ path: `${u.scenario_id}.${s}`, label: s })),
    });
  });

  // 环境变量
  if (envVars.length) {
    sections.push({
      title: '环境', icon: '🌍',
      items: envVars.map((v) => ({ path: v.path, label: v.path })),
    });
  }

  return (
    <div ref={ref} className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        title="插入变量"
        className={`ml-1 px-1 rounded text-fs-aux font-mono leading-4 transition-colors ${
          open ? 'bg-info/30 text-info' : 'text-gray-600 hover:text-info hover:bg-info/10'
        }`}
      >
        {'{x}'}
      </button>

      {open && (
        <div className="absolute z-50 top-6 left-0 w-64 max-h-72 overflow-y-auto bg-surface-2 border border-border rounded-lg shadow-xl">
          <div className="px-2 py-1.5 border-b border-border text-fs-aux text-gray-500 font-medium">
            可用变量（点击插入）
          </div>
          {sections.map((sec) => (
            <div key={sec.title}>
              <div className="px-2 py-1 text-fs-aux text-gray-500 bg-surface-3/50">
                {sec.icon} {sec.title}
              </div>
              {sec.items.map((item) => (
                <button
                  key={item.path}
                  onClick={() => pick(item.path)}
                  className="w-full text-left px-3 py-1 text-fs-body font-mono text-info/70 hover:bg-info/10 hover:text-info"
                >
                  {`{{${item.path}}}`}
                  {item.label !== item.path && (
                    <span className="ml-1.5 text-gray-600 text-fs-aux">{item.label}</span>
                  )}
                </button>
              ))}
            </div>
          ))}
          {/* 数组访问提示 */}
          <div className="px-3 py-2 border-t border-border/50 text-fs-aux text-gray-600">
            <div className="font-medium text-gray-500 mb-0.5">数组访问：</div>
            <code className="block text-info/50">{'{{resp.json.data[0].field}}'}</code>
            <code className="block text-info/50">{'path: "$.data.list[0].id"'}</code>
          </div>
        </div>
      )}
    </div>
  );
}
