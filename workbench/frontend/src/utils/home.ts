/** Home 页纯函数助手（从 pages/Home.tsx 拆出，保持页面文件只导出组件以兼容 react-refresh） */
import type { NavGroup } from '../api';

/** 免权菜单路径（与后端 rbac_store.PUBLIC_MENUS 对齐；零权限提示条判定用）。
 * T-1039：产品对话同为公开菜单（对话双入口），与 /agent 并列 */
export const PUBLIC_MENU_PATHS = ['/agent', '/agent-product'];

/** 时段问候（本地时间小时数 → 问候语） */
export function greeting(hour: number = new Date().getHours()): string {
  if (hour >= 5 && hour < 11) return '早上好';
  if (hour >= 11 && hour < 14) return '中午好';
  if (hour >= 14 && hour < 18) return '下午好';
  if (hour >= 18 && hour < 23) return '晚上好';
  return '深夜好';
}

/** 零权限判定：可见菜单项全部落在公开菜单内（空树不算） */
export function onlyPublicMenus(navTree: NavGroup[]): boolean {
  const items = navTree.flatMap(g => g.items);
  return items.length > 0 && items.every(i => PUBLIC_MENU_PATHS.includes(i.to));
}
