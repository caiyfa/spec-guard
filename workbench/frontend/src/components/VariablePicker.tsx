/** VariablePicker — 变量引用选择器
 *
 * 展示当前位置可用的全部变量：
 * - 前面步骤 save 的变量（含子路径提示）
 * - 上游场景 save 的变量（depends_on 闭包）
 * - 环境变量（env.*）
 * - 数组元素访问示例
 */
import { useState } from 'react';
import type { UpstreamVar } from '../api';

export interface VarItem {
  path: string;       // 完整插值路径（不含 {{}}）
  label: string;      // 显示名
  source: string;     // 来源（步骤名 / 上游场景ID / env）
  example?: string;   // 示例值
}

interface Props {
  /** 当前步骤之前已 save 的变量 [{saveName, stepType}] */
  localVars: { saveName: string; stepType: string }[];
  /** 上游场景可用变量 */
  upstreamVars: UpstreamVar[];
  /** 环境变量 */
  envVars: { path: string; desc: string; example: string }[];
  /** 选中回调（插入 {{path}} 到输入框） */
  onSelect: (path: string) => void;
}

export default function VariablePicker({ localVars, upstreamVars, envVars, onSelect }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  // 构建变量树
  const groups: { title: string; icon: string; items: VarItem[] }[] = [];

  // 1. 当前场景变量（前面步骤 save 的）
  if (localVars.length) {
    const items: VarItem[] = [];
    localVars.forEach((v) => {
      items.push({ path: v.saveName, label: v.saveName, source: v.stepType });
      // 为常见类型展开子路径
      if (v.stepType === 'select_emp') {
        items.push(
          { path: `${v.saveName}.no`, label: '工号', source: v.stepType, example: '90024713' },
          { path: `${v.saveName}.role`, label: '角色', source: v.stepType, example: 'snapshot_rich' },
          { path: `${v.saveName}.activity_id`, label: '活动ID', source: v.stepType, example: '1936' },
          { path: `${v.saveName}.session_id`, label: '会话ID', source: v.stepType, example: '2011' },
          { path: `${v.saveName}.snapshot_type`, label: '快照类型', source: v.stepType, example: 'RESULT' },
        );
      } else if (v.stepType === 'call') {
        items.push(
          { path: `${v.saveName}.status`, label: 'HTTP 状态码', source: v.stepType, example: '200' },
          { path: `${v.saveName}.json`, label: '响应 JSON', source: v.stepType },
        );
      } else if (v.stepType === 'fetch_permission') {
        items.push(
          { path: `${v.saveName}.corp_codes`, label: 'corpCode 列表', source: v.stepType },
          { path: `${v.saveName}.has_any`, label: '是否有权限', source: v.stepType, example: 'true' },
        );
      }
    });
    groups.push({ title: '当前场景变量', icon: '📦', items });
  }

  // 2. 上游场景变量
  upstreamVars.forEach((u) => {
    const items: VarItem[] = u.saves.map((s) => ({
      path: `${u.scenario_id}.${s}`,
      label: `${u.scenario_id}.${s}`,
      source: u.scenario_id,
    }));
    groups.push({ title: `上游: ${u.scenario_id}`, icon: '🔗', items });
  });

  // 3. 环境变量
  if (envVars.length) {
    const items: VarItem[] = envVars.map((v) => ({
      path: v.path, label: v.path, source: 'env', example: v.example,
    }));
    groups.push({ title: '环境变量', icon: '🌍', items });
  }

  return (
    <div className="border border-border/50 rounded bg-surface-3 text-xs">
      {groups.map((g) => (
        <div key={g.title}>
          <button
            onClick={() => setExpanded(expanded === g.title ? null : g.title)}
            className="w-full flex items-center gap-1.5 px-2 py-1.5 text-left text-gray-400 hover:text-gray-200"
          >
            <span>{g.icon}</span>
            <span className="flex-1">{g.title}</span>
            <span className="text-[10px]">{expanded === g.title ? '▾' : '▸'}</span>
          </button>
          {expanded === g.title && (
            <div className="px-2 pb-1.5 space-y-0.5">
              {g.items.map((item) => (
                <button
                  key={item.path}
                  onClick={() => onSelect(`{{${item.path}}}`)}
                  className="w-full text-left px-2 py-1 rounded hover:bg-info/10 group"
                  title={item.example ? `示例: ${item.example}` : undefined}
                >
                  <span className="font-mono text-info/70 group-hover:text-info">{`{{${item.path}}}`}</span>
                  {item.label !== item.path && (
                    <span className="ml-2 text-gray-500">{item.label}</span>
                  )}
                  {item.example && (
                    <span className="ml-2 text-gray-600 text-[10px]">{item.example}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}

      {/* 数组访问指引 */}
      <div className="border-t border-border/50 px-2 py-1.5">
        <button
          onClick={() => setExpanded(expanded === '__array__' ? null : '__array__')}
          className="w-full flex items-center gap-1.5 text-left text-gray-400 hover:text-gray-200"
        >
          <span>📋</span>
          <span className="flex-1">数组元素访问</span>
          <span className="text-[10px]">{expanded === '__array__' ? '▾' : '▸'}</span>
        </button>
        {expanded === '__array__' && (
          <div className="px-2 pb-1.5 space-y-1 text-[10px] text-gray-500">
            <p className="text-gray-400">响应含数组时，用索引或 jsonpath 引用：</p>
            <code className="block font-mono text-info/60">{'{{resp.json.data[0].empNo}}'} <span className="text-gray-600">← 第一个元素</span></code>
            <code className="block font-mono text-info/60">{'{{resp.json.data.gridPlacement[0].activityId}}'} <span className="text-gray-600">← 九宫格第一条</span></code>
            <p className="text-gray-400 mt-1">verify 断言中用 jsonpath：</p>
            <code className="block font-mono text-info/60">{'path: "$.data.gridPlacement[0].activityId"'}</code>
            <code className="block font-mono text-info/60">{'path: "$.data.gridPlacement.length()"'}</code>
          </div>
        )}
      </div>
    </div>
  );
}
