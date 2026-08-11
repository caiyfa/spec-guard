import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation, useNavigate } from 'react-router';
import Dashboard from './pages/Dashboard';
import Lifecycle from './pages/Lifecycle';
import Scenarios from './pages/Scenarios';
import RunControl from './pages/RunControl';
import DagEditor from './pages/DagEditor';
import History from './pages/History';
import Settings from './pages/Settings';
import SpecValidation from './pages/SpecValidation';
import AgentChat from './pages/AgentChat';
import Attribution from './pages/Attribution';
import CoveragePanel from './pages/CoveragePanel';
import WorkspaceCenter from './pages/WorkspaceCenter';
import GitLog from './pages/GitLog';
import Feedback from './pages/Feedback';
import NotifyConfigs from './pages/NotifyConfigs';
import Schedules from './pages/Schedules';
import Drafts from './pages/Drafts';
import Login from './pages/Login';
import AdminUsers from './pages/AdminUsers';
import ZentaoPanel from './pages/ZentaoPanel';
import MaterialsPanel from './pages/MaterialsPanel';
import ScoreFreezePanel from './pages/ScoreFreezePanel';
import EnvironmentConfig from './pages/EnvironmentConfig';
import AuditLog from './pages/AuditLog';
import Knowledge from './pages/Knowledge';  // T-509：知识维护页（一页三区）
import Skills from './pages/Skills';
import GraphPanorama from './pages/GraphPanorama';
import LineageStory from './pages/LineageStory';
import WorkspaceSelector from './components/WorkspaceSelector';
import ThemeSwitcher from './components/ThemeSwitcher';
import { authApi, session } from './api';
import type { CurrentUser } from './api';
import { removeCookie } from './utils/cookie';

const ALL = ['admin', 'tester', 'viewer', 'product'];
const TESTER_UP = ['admin', 'tester'];
const PRODUCT_UP = ['admin', 'tester', 'product'];
const ADMIN_ONLY = ['admin'];

// ── 菜单结构：一级分组 > 二级菜单项，按工作流排序 ──
interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  roles: string[];
}

interface NavGroup {
  label: string;
  icon: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: '总览',
    icon: '📊',
    items: [
      { to: '/', label: '仪表盘', end: true, roles: ALL },
      { to: '/graph', label: '全景图谱', roles: ALL },  // T-071：P-A 图谱支路
      { to: '/lineage', label: '血缘链', roles: ALL },  // T-073：审计追溯 Q1/Q2
    ],
  },
  {
    label: '工作区',
    icon: '🗂',
    items: [
      // K-009：原「工作区管理」+「文档中心」合并为工作区中心，全角色可见（页内按角色显隐操作）
      { to: '/workspace', label: '工作区中心', roles: ALL },
      { to: '/knowledge', label: '知识', roles: TESTER_UP },  // T-509：词条/叙事/经验一页三区
      { to: '/env-config', label: '环境配置', roles: ADMIN_ONLY },  // T-306：环境信息独立维护
      { to: '/settings', label: '系统设置', roles: ADMIN_ONLY },
      { to: '/admin-users', label: '用户管理', roles: ADMIN_ONLY },
      { to: '/audit', label: '审计日志', roles: ADMIN_ONLY },  // T-082：MCP 调用审计
    ],
  },
  {
    label: '需求',
    icon: '📋',
    items: [
      { to: '/spec', label: '合规校验', roles: ALL },
      { to: '/materials', label: '材料管理', roles: ALL },
      { to: '/scores', label: '评分与冻结', roles: ALL },
      { to: '/zentao', label: '禅道集成', roles: ALL },
    ],
  },
  {
    label: '场景',
    icon: '🧩',
    items: [
      { to: '/lifecycle', label: '测试生命周期', roles: ALL },  // K-xxx：台账聚合的完整生命周期监控
      { to: '/coverage', label: '覆盖缺口', roles: ALL },       // T-060：三态泳道 + 生成下一批
      { to: '/plans', label: '场景管理', roles: TESTER_UP },
      { to: '/dag', label: 'DAG 编排', roles: ALL },
    ],
  },
  {
    label: 'Agent',
    icon: '🤖',
    items: [
      { to: '/agent', label: '对话', roles: PRODUCT_UP },
      { to: '/drafts', label: '草稿评审', roles: TESTER_UP },
      { to: '/skills', label: '技能', roles: ALL },
    ],
  },
  {
    label: '执行',
    icon: '▶️',
    items: [
      { to: '/run', label: '测试执行', roles: TESTER_UP },
      { to: '/schedules', label: '定时任务', roles: TESTER_UP },
      { to: '/history', label: '执行记录', roles: ALL },
      { to: '/attribution', label: '失败归因', roles: ALL },
    ],
  },
  {
    label: '反哺',
    icon: '🔄',
    items: [
      { to: '/feedback', label: '反哺闭环', roles: TESTER_UP },
      { to: '/notify', label: '通知配置', roles: TESTER_UP },
    ],
  },
];

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  tester: '测试',
  viewer: '只读',
  product: '产品',
};

// 过滤掉当前角色无权限的分组/菜单项
function filterNavGroups(role: string): NavGroup[] {
  return NAV_GROUPS.map(g => ({
    ...g,
    items: g.items.filter(i => i.roles.includes(role)),
  })).filter(g => g.items.length > 0);
}

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
      .catch(() => {
        if (!window.location.pathname.startsWith('/login')) {
          session.clearToken();
          window.location.href = '/login';
        }
      })
      .finally(() => setLoading(false));
  }, [isLoginPage]);

  const handleLogout = async () => {
    let uacLogoutUrl = '';
    try {
      const r = await authApi.logout();
      uacLogoutUrl = r.uac_logout_url || '';
    } catch { /* 忽略，本地登出优先 */ }
    session.clearToken();
    // 清除 fesso_access_token cookie（跨子域共享）
    const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    removeCookie('fesso_access_token', { path: '/', domain: isLocalhost ? undefined : '.fehorizon.com' });
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

  return (
    <BrowserRouter>
      <AppContent user={user} onLogout={handleLogout} />
    </BrowserRouter>
  );
}

function AppContent({ user, onLogout }: { user: CurrentUser; onLogout: () => void }) {
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(() => {
    return localStorage.getItem('sg_drawer_open') !== 'false';
  });
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => {
    // 默认展开当前路由所在分组
    const groups = filterNavGroups(user.role);
    const current = groups.find(g =>
      g.items.some(i => i.to === location.pathname || (i.to !== '/' && location.pathname.startsWith(i.to)))
    );
    return new Set(current ? [current.label] : []);
  });

  const noPadding = location.pathname === '/agent';
  const visibleGroups = filterNavGroups(user.role);

  const toggleDrawer = () => {
    const next = !drawerOpen;
    setDrawerOpen(next);
    localStorage.setItem('sg_drawer_open', String(next));
  };

  const toggleGroup = (label: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  // 判断分组是否应该高亮（包含当前路由）
  const isGroupActive = (group: NavGroup) =>
    group.items.some(i =>
      i.to === location.pathname ||
      (i.to !== '/' && location.pathname.startsWith(i.to))
    );

  return (
    <div className="flex h-screen overflow-hidden">
      {/* 抽屉式侧边栏 */}
      <aside
        style={{ width: drawerOpen ? '208px' : '0px', minWidth: 0 }}
        className="flex-shrink-0 bg-surface-2 border-r border-border flex flex-col overflow-hidden"
      >
        {/* Logo 区 */}
        <div className="p-4 border-b border-border flex-shrink-0">
          <h1 className="text-sm font-bold brand-gradient whitespace-nowrap">🛡 SpecGuard</h1>
          <p className="text-[11px] text-gray-500 mt-0.5 whitespace-nowrap">场景测试与AI智能编排平台</p>
        </div>

        {/* 菜单区 */}
        <nav className="flex-1 p-1.5 overflow-y-auto">
          {visibleGroups.map(group => {
            const isExpanded = expandedGroups.has(group.label);
            const isActive = isGroupActive(group);
            const isSingle = group.items.length === 1;
            const item = group.items[0];

            // 单项分组：直接渲染为链接
            if (isSingle) {
              return (
                <NavLink
                  key={group.label}
                  to={item.to}
                  end={item.end}
                  className={({ isActive: a }) =>
                    `flex items-center gap-2 px-2.5 py-2 rounded-md text-sm transition-colors whitespace-nowrap ${
                      a
                        ? 'bg-info/10 text-info font-medium'
                        : 'text-gray-400 hover:text-gray-200 hover:bg-surface-3'
                    }`
                  }
                >
                  <span className="text-xs">{group.icon}</span>
                  <span>{item.label}</span>
                </NavLink>
              );
            }

            // 多项分组：可折叠
            return (
              <div key={group.label} className="mb-0.5">
                <button
                  onClick={() => toggleGroup(group.label)}
                  className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-sm transition-colors whitespace-nowrap ${
                    isActive
                      ? 'text-gray-200 font-medium'
                      : 'text-gray-500 hover:text-gray-300 hover:bg-surface-3'
                  }`}
                >
                  <span className="text-xs">{group.icon}</span>
                  <span className="flex-1 text-left">{group.label}</span>
                  <span className="text-[10px] text-gray-600">{isExpanded ? '▼' : '▶'}</span>
                </button>
                {isExpanded && (
                  <div className="ml-3 border-l border-border/50 pl-1 mt-0.5 space-y-0.5">
                    {group.items.map(item => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        end={item.end}
                        className={({ isActive: a }) =>
                          `block px-2.5 py-1.5 rounded text-xs transition-colors whitespace-nowrap ${
                            a
                              ? 'bg-info/10 text-info font-medium'
                              : 'text-gray-500 hover:text-gray-300 hover:bg-surface-3'
                          }`
                        }
                      >
                        {item.label}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div className="p-3 border-t border-border text-[10px] text-gray-600 flex-shrink-0 whitespace-nowrap">
          engine 不可变 · 仅读写 YAML + reports
        </div>
      </aside>

      {/* 主区：顶栏 + 内容 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 顶栏：抽屉开关 + 工作区选择器 + 用户区 */}
        <header className="flex-shrink-0 h-12 bg-surface-2 border-b border-border flex items-center justify-between px-4">
          <div className="flex items-center gap-3">
            {/* 抽屉开关 */}
            <button
              onClick={toggleDrawer}
              className="text-gray-400 hover:text-gray-200 transition-colors p-1 rounded hover:bg-surface-3"
              title={drawerOpen ? '收起菜单' : '展开菜单'}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2">
                {drawerOpen ? (
                  <path d="M3 3 L15 3 M3 9 L15 9 M3 15 L15 15" />
                ) : (
                  <path d="M3 3 L15 3 M3 9 L15 9 M3 15 L15 15" />
                )}
              </svg>
            </button>
            <WorkspaceSelector user={user} />
          </div>
          <div className="flex items-center gap-3 text-sm">
            <ThemeSwitcher />
            <span className="text-gray-300">{user.name}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded ${
              user.role === 'admin' ? 'bg-purple-900/50 text-purple-300'
              : user.role === 'tester' ? 'bg-info/15 text-info'
              : user.role === 'product' ? 'bg-amber-900/50 text-amber-300'
              : 'bg-gray-700 text-gray-400'
            }`}>{ROLE_LABEL[user.role] || user.role}</span>
            <button
              onClick={onLogout}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              登出
            </button>
          </div>
        </header>

        {/* 主内容区 */}
        <main className={`flex-1 overflow-hidden ${noPadding ? '' : 'overflow-y-auto p-6'}`}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/graph" element={<GraphPanorama />} />  {/* T-071：全景图谱（三镜头+源头定位） */}
            <Route path="/lineage" element={<LineageStory />} />  {/* T-073：血缘链审计追溯 */}
            <Route path="/lifecycle" element={<Lifecycle />} />  {/* K-xxx：测试生命周期监控 */}
            <Route path="/spec" element={<SpecValidation />} />
            <Route path="/materials" element={<MaterialsPanel />} />
            <Route path="/scores" element={<ScoreFreezePanel />} />
            <Route path="/zentao" element={<ZentaoPanel />} />
            <Route path="/plans" element={<Scenarios />} />
            <Route path="/coverage" element={<CoveragePanel />} />
            <Route path="/knowledge" element={<Knowledge />} />  {/* T-509：知识维护页 */}
            <Route path="/run" element={<RunControl />} />
            <Route path="/dag" element={<DagEditor />} />
            <Route path="/history" element={<History />} />
            <Route path="/agent" element={<AgentChat />} />
            <Route path="/drafts" element={<Drafts />} />
            {/* /scenario-create 已合并到 /plans */}
            <Route path="/scenario-create" element={<RedirectToPlans />} />
            {/* K-009：/spec-center 已合并到 /workspace（工作区中心） */}
            <Route path="/spec-center" element={<RedirectToWorkspace />} />
            <Route path="/attribution" element={<Attribution />} />
            <Route path="/workspace" element={<WorkspaceCenter role={user.role} />} />
            <Route path="/workspace/git-log" element={<GitLog />} />  {/* git 提交历史（SourceTree 风格） */}
            <Route path="/feedback" element={<Feedback />} />
            <Route path="/notify" element={<NotifyConfigs />} />
                        <Route path="/schedules" element={<Schedules />} />
            <Route path="/admin-users" element={<AdminUsers />} />
            <Route path="/env-config" element={<EnvironmentConfig />} />  {/* T-306：环境信息独立维护 */}
            <Route path="/audit" element={<AuditLog />} />  {/* T-082：MCP 调用审计 */}
            <Route path="/skills" element={<Skills />} />  {/* T-080：Skill 注册表 */}
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

function RedirectToPlans() {
  const navigate = useNavigate();
  useEffect(() => { navigate('/plans'); }, [navigate]);
  return null;
}

function RedirectToWorkspace() {
  const navigate = useNavigate();
  useEffect(() => { navigate('/workspace'); }, [navigate]);
  return null;
}
