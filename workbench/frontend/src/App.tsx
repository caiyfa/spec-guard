import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation, useNavigate } from 'react-router';
import Dashboard from './pages/Dashboard';
import Lifecycle from './pages/Lifecycle';
import Scenarios from './pages/Scenarios';
import RunControl from './pages/RunControl';
import DagEditor from './pages/DagEditor';
import History from './pages/History';
import DbConsole from './pages/DbConsole';
import Settings from './pages/Settings';
import AgentChat from './pages/AgentChat';
import Home from './pages/Home';
import Feedback from './pages/Feedback';
import Drafts from './pages/Drafts';
import Login from './pages/Login';
import AdminUsers from './pages/AdminUsers';
import FeishuPool from './pages/FeishuPool';
import AuditLog from './pages/AuditLog';
import MenuRoles from './pages/MenuRoles';
import SystemConfig from './pages/SystemConfig';
import MyActivity from './pages/MyActivity';
import GraphPanorama from './pages/GraphPanorama';
import ScenarioQuality from './pages/ScenarioQuality';
import WorkspaceSelector from './components/WorkspaceSelector';
import ThemeSwitcher from './components/ThemeSwitcher';
import { authApi, session, menusApi } from './api';
import type { CurrentUser, NavGroup } from './api';
import { removeCookie } from './utils/cookie';

// 隐藏 Redirect 路由的目标菜单（允许访问时按目标校验）
// T-996 菜单收缩：被收编/删除的页面路由全部 301 到幸存页（带 tab 深链）
const REDIRECT_TARGETS: Record<string, string> = {
  '/scenario-create': '/plans',
  '/spec-center': '/dashboard',
  '/lineage': '/graph',                    // 血缘链并入全景图谱镜头
  '/coverage': '/lifecycle?tab=coverage',  // 覆盖缺口并入生命周期页
  '/schedules': '/history?tab=schedules',  // 定时任务并入执行中心
  '/attribution': '/history?tab=attribution',  // 失败归因并入执行中心
  '/notify': '/feedback?tab=notify',       // 通知配置并入反哺闭环
  '/skills': '/agent',                     // 技能收对话页签
  '/materials': '/agent-product',          // 材料管理收操作台页签（T-1039：产品侧）
  '/scores': '/agent-product',             // 评分冻结收操作台页签（T-1039：产品侧）
  '/zentao': '/agent-product',             // 禅道收操作台页签（T-1039：产品侧）
  '/spec': '/agent',                       // 合规校验收对话页签
  '/knowledge': '/agent',                  // 知识收对话页签
  '/workspace/git-log': '/system-config',  // GitLog 已删除，回系统配置（T-1010 三栏合一）
  '/workspace': '/system-config',          // T-1010：工作区中心并入系统配置栏2
  '/systems': '/system-config',            // T-1010：系统包管理并入系统配置栏1
  '/env-config': '/system-config',         // T-1010：环境配置并入系统配置栏3
};

// 免权页面（登录即用，无需菜单授权）：路由守卫直接放行
const PUBLIC_PATHS = ['/'];

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  tester: '测试',
  viewer: '只读',
  product: '产品',
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
  // RBAC：登录后拉取当前用户可见菜单树（动态渲染 + 路由守卫数据源）
  const [navTree, setNavTree] = useState<NavGroup[]>([]);
  const [navLoaded, setNavLoaded] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => {
    // 默认展开当前路由所在分组（navTree 就绪后重新计算）
    return new Set();
  });

  const [navError, setNavError] = useState(false);
  const loadNav = () => {
    setNavError(false);
    menusApi.me()
      .then(r => setNavTree(r.groups))
      .catch(() => { setNavTree([]); setNavError(true); })
      .finally(() => setNavLoaded(true));
  };
  useEffect(() => { loadNav(); }, []);

  // 路由变化时默认展开当前路由所在分组（不重复拉菜单树）
  useEffect(() => {
    if (!navTree.length) return;
    const current = navTree.find(g =>
      g.items.some(i => i.to === location.pathname || (i.to !== '/' && location.pathname.startsWith(i.to)))
    );
    if (current) setExpandedGroups(prev => prev.has(current.label) ? prev : new Set([current.label]));
  }, [location.pathname, navTree]);

  const noPadding = location.pathname.startsWith('/agent');  // T-1039：/agent 与 /agent-product 双对话页均无 padding
  const visibleGroups = navTree;

  // 路由守卫：当前 path 不在可见菜单（含隐藏 Redirect 目标）→ 无权限页
  const allowedPaths = new Set(navTree.flatMap(g => g.items.map(i => i.to)));
  const effectivePath = REDIRECT_TARGETS[location.pathname] ?? location.pathname;
  const pathAllowed =
    PUBLIC_PATHS.includes(effectivePath) ||
    allowedPaths.has(effectivePath) ||
    allowedPaths.has(effectivePath.replace(/\/$/, '')) ||
    (effectivePath !== '/' && [...allowedPaths].some(p => p !== '/' && effectivePath.startsWith(p)));
  const noAccess = navLoaded && !pathAllowed;

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
        {/* Logo 区（点击回首页） */}
        <NavLink to="/" className="block p-4 border-b border-border flex-shrink-0 hover:bg-surface-3/50 transition-colors" title="返回首页">
          <h1 className="text-sm font-bold brand-gradient whitespace-nowrap">🛡 SpecGuard</h1>
          <p className="text-[11px] text-gray-500 mt-0.5 whitespace-nowrap">场景测试与AI智能编排平台</p>
        </NavLink>

        {/* 菜单区 */}
        <nav className="flex-1 p-1.5 overflow-y-auto">
          {/* 静态首页入口（免权，不参与菜单授权） */}
          <NavLink
            to="/"
            end
            className={({ isActive: a }) =>
              `flex items-center gap-2 px-2.5 py-2 rounded-md text-sm transition-colors whitespace-nowrap mb-0.5 ${
                a
                  ? 'bg-info/10 text-info font-medium'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-surface-3'
              }`
            }
          >
            <span className="text-xs">🏠</span>
            <span>首页</span>
          </NavLink>
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
                  <span className="text-fs-aux text-gray-600">{isExpanded ? '▼' : '▶'}</span>
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

        <div className="p-3 border-t border-border text-fs-aux text-gray-600 flex-shrink-0 whitespace-nowrap">
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
            }`}
              title={(user.roles ?? []).join(', ')}>
              {ROLE_LABEL[user.role] || user.role}
              {(user.roles ?? []).length > 1 ? ` +${user.roles.length - 1}` : ''}
            </span>
            <button
              onClick={onLogout}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              登出
            </button>
          </div>
        </header>

        {/* 主内容区：无权限时渲染占位页（RBAC 路由守卫） */}
        {noAccess ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-500">
            <span className="text-5xl">🔒</span>
            <p className="text-sm">无权限访问该页面，请联系管理员开通菜单授权</p>
            <NavLink to="/" className="text-xs text-info hover:underline">返回首页</NavLink>
          </div>
        ) : (
          <main className={`flex-1 overflow-hidden ${noPadding ? '' : 'overflow-y-auto p-6'}`}>
            <Routes>
              {/* 首页 = Home（登录即用，免菜单权限，守卫 PUBLIC_PATHS 放行）；
                  T-1040：对话按用途拆双菜单——测试对话 /agent · 产品对话 /agent-product（固定用途锁定）。
                  两条路由的 AgentChat 必须带互异 key：React 对同位置同类型组件复用实例，
                  无 key 时 SPA 菜单切换不重挂载，分侧交换（ensureSideStore）/深链 ?session=
                  消费/上次会话恢复三处挂载期逻辑整体旁路（T-1040 主库验收实锤串扰）。
                  共享 WS 是模块级 _store.ws，重挂载只采纳连接不断连。 */}
              <Route path="/" element={<Home user={user} navTree={navTree} navLoaded={navLoaded} navError={navError} onRetryNav={loadNav} />} />
              <Route path="/agent" element={<AgentChat key="agent-test" fixedPurpose="test_workbench" />} />
              <Route path="/agent-product" element={<AgentChat key="agent-product" fixedPurpose="requirement_interview" />} />
              <Route path="/dashboard" element={<Dashboard />} />  {/* 仪表盘（原首页） */}
              <Route path="/graph" element={<GraphPanorama />} />  {/* T-071：全景图谱（三镜头+源头定位） */}

              <Route path="/lifecycle" element={<Lifecycle />} />  {/* K-xxx：测试生命周期监控 */}

              <Route path="/feishu-pool" element={<FeishuPool />} />  {/* T-929：飞书话题总览（T-1003 改名） */}

              <Route path="/plans" element={<Scenarios />} />
              <Route path="/scenario-quality" element={<ScenarioQuality role={user.role} />} />  {/* T-1035：测试用例管理（详情编辑/试跑按角色门控） */}

              <Route path="/run" element={<RunControl />} />
              <Route path="/dag" element={<DagEditor />} />
              <Route path="/history" element={<History />} />
              <Route path="/drafts" element={<Drafts />} />
              <Route path="/feedback" element={<Feedback />} />
              <Route path="/db-console" element={<DbConsole />} />  {/* DB 证据面板（设计 2026-08-25） */}
              <Route path="/admin-users" element={<AdminUsers />} />
              <Route path="/audit" element={<AuditLog />} />  {/* T-082：MCP 调用审计 */}
              <Route path="/menu-roles" element={<MenuRoles />} />  {/* RBAC：菜单管理 + 角色授权 */}
              <Route path="/settings" element={<Settings />} />  {/* T-1010：基础设置（数据库 tab 已并入系统配置） */}
              <Route path="/system-config" element={<SystemConfig role={user.role} />} />  {/* T-1010：系统配置三栏（系统/工作区/环境配置） */}
              <Route path="/my-activity" element={<MyActivity />} />  {/* T-1000：我的活动（产出/会话/工具/执行） */}
              {/* T-996：被收编/删除的路由统一重定向（矩阵见 REDIRECT_TARGETS） */}
              {Object.entries(REDIRECT_TARGETS).map(([from, to]) => (
                <Route key={from} path={from} element={<RedirectTo to={to} />} />
              ))}
            </Routes>
          </main>
        )}
      </div>
    </div>
  );
}

function RedirectTo({ to }: { to: string }) {
  const navigate = useNavigate();
  useEffect(() => { navigate(to); }, [navigate, to]);
  return null;
}
