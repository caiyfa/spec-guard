import { useEffect, useState } from 'react';
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
import Drafts from './pages/Drafts';
import Login from './pages/Login';
import AdminUsers from './pages/AdminUsers';
import WorkspaceSelector from './components/WorkspaceSelector';
import { authApi, session } from './api';
import type { CurrentUser } from './api';

const ALL = ['admin', 'tester', 'viewer'];
const TESTER_UP = ['admin', 'tester'];
const ADMIN_ONLY = ['admin'];

const NAV = [
  { to: '/', label: '📊 总览', end: true, roles: ALL },
  { to: '/spec', label: '🛡 Spec 校验', roles: ALL },
  { to: '/plans', label: '📋 测试场景管理', roles: TESTER_UP },
  { to: '/dag', label: '🔀 DAG 编排', roles: ALL },
  { to: '/run', label: '▶️ 测试执行', roles: TESTER_UP },
  { to: '/history', label: '📈 历史对比', roles: ALL },
  { to: '/agent', label: '🤖 Agent 生成', roles: TESTER_UP },
  { to: '/drafts', label: '📝 草稿评审', roles: TESTER_UP },
  { to: '/spec-center', label: '📄 Spec 文档', roles: ALL },
  { to: '/attribution', label: '🔍 失败归因', roles: ALL },
  { to: '/workspace', label: '🗂 工作区', roles: ADMIN_ONLY },
  { to: '/feedback', label: '🔄 反哺闭环', roles: TESTER_UP },
  { to: '/admin-users', label: '👥 用户', roles: ADMIN_ONLY },
  { to: '/settings', label: '⚙️ 环境设置', roles: ADMIN_ONLY },
];

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  tester: '测试',
  viewer: '只读',
};

export default function App() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const isLoginPage = window.location.pathname === '/login';

  useEffect(() => {
    if (isLoginPage) {
      setLoading(false);
      return;
    }
    if (!session.getToken()) {
      window.location.href = '/login';
      return;
    }
    authApi.me()
      .then(setUser)
      .catch(() => { /* 401 由 api.ts 统一处理 */ })
      .finally(() => setLoading(false));
  }, [isLoginPage]);

  const handleLogout = async () => {
    let uacLogoutUrl = '';
    try {
      const r = await authApi.logout();
      uacLogoutUrl = r.uac_logout_url || '';
    } catch { /* 忽略，本地登出优先 */ }
    session.clearToken();
    if (user?.auth_mode === 'uac' && uacLogoutUrl) {
      window.location.href = uacLogoutUrl;
    } else {
      window.location.href = '/login';
    }
  };

  if (isLoginPage) {
    return (
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </BrowserRouter>
    );
  }

  if (loading || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-500 text-sm">
        加载用户信息…
      </div>
    );
  }

  const visibleNav = NAV.filter(n => n.roles.includes(user.role));

  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden">
        {/* 侧边栏 */}
        <aside className="w-52 flex-shrink-0 bg-surface-2 border-r border-border flex flex-col">
          <div className="p-4 border-b border-border">
            <h1 className="text-sm font-bold text-info">🛡 SpecGuard</h1>
            <p className="text-[11px] text-gray-500 mt-0.5">测试流水线工作台</p>
          </div>
          <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
            {visibleNav.map((n) => (
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

        {/* 主区：顶栏 + 内容 */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* 顶栏：工作区选择器 + 用户区 */}
          <header className="flex-shrink-0 h-12 bg-surface-2 border-b border-border flex items-center justify-between px-4">
            <WorkspaceSelector user={user} />
            <div className="flex items-center gap-3 text-sm">
              <span className="text-gray-300">{user.name}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded ${
                user.role === 'admin' ? 'bg-purple-900/50 text-purple-300'
                : user.role === 'tester' ? 'bg-info/15 text-info'
                : 'bg-gray-700 text-gray-400'
              }`}>{ROLE_LABEL[user.role] || user.role}</span>
              <button
                onClick={handleLogout}
                className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
              >
                登出
              </button>
            </div>
          </header>

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
              <Route path="/drafts" element={<Drafts />} />
              <Route path="/spec-center" element={<SpecCenter />} />
              <Route path="/attribution" element={<Attribution />} />
              <Route path="/workspace" element={<WorkspaceSettings />} />
              <Route path="/feedback" element={<Feedback />} />
              <Route path="/admin-users" element={<AdminUsers />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
