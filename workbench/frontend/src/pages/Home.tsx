/** Home — 登录后首页（导航枢纽型 · 免菜单权限）
 *
 * 设计：docs/superpowers/specs/2026-08-18-登录首页-design.md
 * 数据全部来自免权通道：user（auth/me）与 navTree（menus/me）由 App 层注入，本页零请求。
 * K-044 兼容：不涂刷页面级不透明背景，自定义背景图三层模型（图片层→罩层→内容层）自然透出。
 */
import { NavLink } from 'react-router';
import type { CurrentUser, NavGroup } from '../api';
import { greeting, onlyPublicMenus } from '../utils/home';

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  tester: '测试',
  viewer: '只读',
  product: '产品',
};

// 与 App.tsx 顶栏角色徽章同一套配色
const ROLE_BADGE: Record<string, string> = {
  admin: 'bg-purple-900/50 text-purple-300',
  tester: 'bg-info/15 text-info',
  product: 'bg-amber-900/50 text-amber-300',
  viewer: 'bg-gray-700 text-gray-400',
};

export default function Home({ user, navTree, navLoaded, navError, onRetryNav }: {
  user: CurrentUser;
  navTree: NavGroup[];
  navLoaded: boolean;
  navError: boolean;
  onRetryNav: () => void;
}) {
  const groups = navTree.filter(g => g.items.length > 0);
  return (
    <div className="max-w-6xl mx-auto space-y-4">
      {/* Hero：问候 + 身份 + 主 CTA（光晕为半透明叠加层，背景图开启时与罩层自然融合） */}
      <section className="relative overflow-hidden rounded-xl border border-border bg-surface-2">
        <div className="absolute inset-0 pointer-events-none" style={{
          background: `radial-gradient(500px 180px at 18% 0%, rgb(var(--info) / 0.14), transparent 65%),
                       radial-gradient(420px 200px at 88% 110%, rgb(var(--blocked) / 0.10), transparent 60%)`,
        }} />
        <div className="relative px-7 py-7">
          <h2 className="text-xl font-bold">
            <span className="brand-gradient">👋 {greeting()}，{user.name}</span>
            <span
              className={`ml-2 align-middle text-fs-body px-1.5 py-0.5 rounded ${ROLE_BADGE[user.role] ?? ROLE_BADGE.viewer}`}
              title={(user.roles ?? []).join(', ')}
            >
              {ROLE_LABEL[user.role] || user.role}
              {(user.roles ?? []).length > 1 ? ` +${user.roles.length - 1}` : ''}
            </span>
          </h2>
          <p className="text-fs-body text-gray-500 mt-1.5">契约驱动的场景测试与 AI 智能编排平台</p>
          <NavLink to="/agent" className="btn-primary mt-4">
            💬 开始 Agent 对话
          </NavLink>
        </div>
      </section>

      {/* 零权限提示条（D3） */}
      {navLoaded && !navError && onlyPublicMenus(navTree) && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn text-fs-body px-4 py-2.5">
          ℹ️ 当前账号暂未开通功能菜单，可先在 Agent 对话中体验；更多功能请联系管理员在「菜单管理 → 角色授权」中开通
        </div>
      )}

      {/* 功能入口卡区：数据即权限（menus/me 实时返回） */}
      {!navLoaded ? (
        <div className="text-center text-gray-500 text-fs-body py-10">菜单加载中…</div>
      ) : navError ? (
        <div className="text-center py-10 space-y-3">
          <p className="text-gray-500 text-fs-body">菜单加载失败</p>
          <button onClick={onRetryNav} className="btn-primary">重试</button>
        </div>
      ) : (
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {groups.map(g => (
            <div key={g.label} className="card-hover">
              <div className="text-sm font-medium text-gray-200 mb-2">
                <span className="mr-1.5">{g.icon}</span>{g.label}
              </div>
              <div className="space-y-0.5">
                {g.items.map(i => (
                  <NavLink
                    key={i.to}
                    to={i.to}
                    className="block text-fs-body text-gray-500 hover:text-info hover:bg-info/5 rounded px-2 py-1.5 transition-colors"
                  >
                    {i.label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
