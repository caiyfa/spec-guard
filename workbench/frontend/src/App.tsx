import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Plans from './pages/Plans';
import RunControl from './pages/RunControl';
import DagEditor from './pages/DagEditor';
import History from './pages/History';
import Settings from './pages/Settings';
import SpecValidation from './pages/SpecValidation';
import AgentChat from './pages/AgentChat';
import SpecCenter from './pages/SpecCenter';
import Attribution from './pages/Attribution';
import WorkspaceSettings from './pages/WorkspaceSettings';
import Feedback from './pages/Feedback';

const NAV = [
  { to: '/', label: '📊 总览', end: true },
  { to: '/spec', label: '🛡 Spec 校验' },
  { to: '/plans', label: '📋 测试场景管理' },
  { to: '/dag', label: '🔀 DAG 编排' },
  { to: '/run', label: '▶️ 测试执行' },
  { to: '/history', label: '📈 历史对比' },
  { to: '/agent', label: '🤖 Agent 生成' },
  { to: '/spec-center', label: '📄 Spec 文档' },
  { to: '/attribution', label: '🔍 失败归因' },
  { to: '/workspace', label: '🗂 工作区' },
  { to: '/feedback', label: '🔄 反哺闭环' },
  { to: '/settings', label: '⚙️ 环境设置' },
];

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden">
        {/* 侧边栏 */}
        <aside className="w-52 flex-shrink-0 bg-surface-2 border-r border-border flex flex-col">
          <div className="p-4 border-b border-border">
            <h1 className="text-sm font-bold text-info">🛡 SpecGuard</h1>
            <p className="text-[11px] text-gray-500 mt-0.5">测试流水线工作台</p>
          </div>
          <nav className="flex-1 p-2 space-y-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `block px-3 py-2 rounded-md text-sm transition-colors ${
                    isActive
                      ? 'bg-info/10 text-info font-medium'
                      : 'text-gray-400 hover:text-gray-200 hover:bg-surface-3'
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="p-3 border-t border-border text-[10px] text-gray-600">
            engine 不可变 · 仅读写 YAML + reports
          </div>
        </aside>

        {/* 主内容区 */}
        <main className="flex-1 overflow-y-auto p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/spec" element={<SpecValidation />} />
            <Route path="/plans" element={<Plans />} />
            <Route path="/run" element={<RunControl />} />
            <Route path="/dag" element={<DagEditor />} />
            <Route path="/history" element={<History />} />
            <Route path="/agent" element={<AgentChat />} />
            <Route path="/spec-center" element={<SpecCenter />} />
            <Route path="/attribution" element={<Attribution />} />
            <Route path="/workspace" element={<WorkspaceSettings />} />
            <Route path="/feedback" element={<Feedback />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
