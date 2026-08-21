/** api/auth — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

// ── 认证 ──
export interface CurrentUser {
  emp_no: string;
  name: string;
  role: 'admin' | 'tester' | 'viewer' | 'product';
  roles?: string[];  // v1.8 多角色集（RBAC：菜单授权按角色集并集）
  default_workspace: string;
  auth_mode: 'uac' | 'mock';
}

export const authApi = {
  config: () => request<{ auth_mode: string; uac_base: string; sso_base: string; sso_app_id: string; uac_logout_url: string }>('/auth/config'),
  me: () => request<CurrentUser>('/auth/me'),
  mockLogin: (emp_no: string, name = '') =>
    request<{ ok: boolean; token: string; user: any }>('/auth/mock-login', {
      method: 'POST',
      body: JSON.stringify({ emp_no, name }),
    }),
  logout: () => request<{ ok: boolean; uac_logout_url: string }>('/auth/logout', { method: 'POST' }),
};

// ── 用户与授权管理（admin）──
export interface UserItem {
  emp_no: string;
  name: string;
  role: string;
  roles: string[];  // v1.8 多角色集
  default_workspace: string;
  created_at: string;
  last_login_at: string;
}

export interface GrantItem {
  id: number;
  workspace_name: string;
  emp_no: string;
  granted_by: string;
  created_at: string;
}

export const usersApi = {
  list: () => request<{ users: UserItem[] }>('/users'),
  setRole: (emp_no: string, role: string) =>
    request<{ ok: boolean }>(`/users/${encodeURIComponent(emp_no)}/role`, {
      method: 'PUT',
      body: JSON.stringify({ role }),
    }),
  setRoles: (emp_no: string, roles: string[]) =>
    request<{ ok: boolean }>(`/users/${encodeURIComponent(emp_no)}/role`, {
      method: 'PUT',
      body: JSON.stringify({ roles }),
    }),
  grants: () => request<{ grants: GrantItem[] }>('/users/grants'),
  grant: (emp_no: string, workspace_name: string) =>
    request<{ ok: boolean }>(`/users/${encodeURIComponent(emp_no)}/grants`, {
      method: 'POST',
      body: JSON.stringify({ workspace_name }),
    }),
  revoke: (emp_no: string, workspace_name: string) =>
    request<{ ok: boolean }>(`/users/${encodeURIComponent(emp_no)}/grants/${encodeURIComponent(workspace_name)}`, {
      method: 'DELETE',
    }),
  setDefaultWorkspace: (workspace_name: string) =>
    request<{ ok: boolean; default_workspace: string }>('/users/me/default-workspace', {
      method: 'PUT',
      body: JSON.stringify({ workspace_name }),
    }),
  auditLog: (limit = 100) => request<{ entries: any[] }>(`/users/audit-log?limit=${limit}`),
};

// ── 菜单 / 角色 RBAC ──
export interface NavMenuItem {
  to: string;
  label: string;
  end?: boolean;
}
export interface NavGroup {
  label: string;
  icon: string;
  items: NavMenuItem[];
}
export interface MenuRecord {
  menu_key: string;
  label: string;
  icon: string;
  path: string;
  parent_key: string;
  sort: number;
  visible: boolean;
  is_system: boolean;
  is_public: boolean;  // 公开菜单：登录即用，无需授权（首页对话）
}
export interface RoleRecord {
  role_key: string;
  label: string;
  is_builtin: boolean;
  sort: number;
}

export const menusApi = {
  me: () => request<{ groups: NavGroup[] }>('/menus/me'),
  list: () => request<{ menus: MenuRecord[] }>('/menus'),
  create: (body: Partial<MenuRecord>) =>
    request<{ ok: boolean }>('/menus', { method: 'POST', body: JSON.stringify(body) }),
  update: (menu_key: string, body: Partial<MenuRecord>) =>
    request<{ ok: boolean }>(`/menus/${encodeURIComponent(menu_key)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  remove: (menu_key: string) =>
    request<{ ok: boolean }>(`/menus/${encodeURIComponent(menu_key)}`, { method: 'DELETE' }),
};

export const rolesApi = {
  list: () => request<{ roles: RoleRecord[] }>('/roles'),
  create: (role_key: string, label: string, sort = 0) =>
    request<{ ok: boolean }>('/roles', {
      method: 'POST',
      body: JSON.stringify({ role_key, label, sort }),
    }),
  update: (role_key: string, label: string, sort = 0) =>
    request<{ ok: boolean }>(`/roles/${encodeURIComponent(role_key)}`, {
      method: 'PUT',
      body: JSON.stringify({ label, sort }),
    }),
  remove: (role_key: string) =>
    request<{ ok: boolean }>(`/roles/${encodeURIComponent(role_key)}`, { method: 'DELETE' }),
  getMenus: (role_key: string) =>
    request<{ menu_keys: string[] }>(`/roles/${encodeURIComponent(role_key)}/menus`),
  setMenus: (role_key: string, menu_keys: string[]) =>
    request<{ ok: boolean }>(`/roles/${encodeURIComponent(role_key)}/menus`, {
      method: 'PUT',
      body: JSON.stringify({ menu_keys }),
    }),
};

