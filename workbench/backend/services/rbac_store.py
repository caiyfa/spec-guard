"""RBAC 存储层：menus / roles / role_menus 三表（菜单管理 + 角色授权）。

- 与 user_store 同构：SQLite 复用 workbench/backend/data/workbench.db
- 所有函数支持 db_path 覆盖（测试用临时库）
- 不导入 user_store（delete_role 的用户引用检查内联 SQL 查 users 表），
  user_store 单向导入本模块，避免循环导入
- 审计写入前 ensure audit_log 表（幂等），不依赖 user_store.init_db 顺序
"""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "data" / "workbench.db"

_LOCK = threading.RLock()

# 系统保护菜单：admin 授权不可移除（自举保底，防管理员锁死）
SYSTEM_MENUS = ("menu-menu-manage", "menu-users")
# 公开菜单：登录即用，无需任何角色/菜单授权（首页对话页免权）
PUBLIC_MENUS = ("menu-agent",)
# 内置角色：不可删、key 不可改
BUILTIN_ROLES = ("admin", "tester", "viewer", "product")
ROLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
MENU_KEY_RE = re.compile(r"^(group|menu)-[a-z0-9-]{1,63}$")

# ── 种子数据：菜单树（与历史 App.tsx NAV_GROUPS 一致；全新配置 = 零角色授权）──
# (menu_key, label, icon, path, parent_key, sort, visible, is_system)
SEED_MENUS: list[tuple] = [
    ("group-overview", "总览", "📊", "", "", 0, 1, 0),
    ("menu-dashboard", "仪表盘", "", "/dashboard", "group-overview", 0, 1, 0),
    ("menu-graph", "全景图谱", "", "/graph", "group-overview", 1, 1, 0),
    ("menu-lineage", "血缘链", "", "/lineage", "group-overview", 2, 1, 0),
    ("group-workspace", "工作区", "🗂", "", "", 1, 1, 0),
    ("menu-workspace", "工作区中心", "", "/workspace", "group-workspace", 0, 1, 0),
    ("menu-knowledge", "知识", "", "/knowledge", "group-workspace", 1, 1, 0),
    ("menu-env-config", "环境配置", "", "/env-config", "group-workspace", 2, 1, 0),
    ("menu-settings", "系统设置", "", "/settings", "group-workspace", 3, 1, 0),
    ("menu-users", "用户管理", "", "/admin-users", "group-workspace", 4, 1, 1),
    ("menu-audit", "审计日志", "", "/audit", "group-workspace", 5, 1, 0),
    ("menu-menu-manage", "菜单管理", "", "/menu-roles", "group-workspace", 6, 1, 1),
    ("group-requirement", "需求", "📋", "", "", 2, 1, 0),
    ("menu-spec", "合规校验", "", "/spec", "group-requirement", 0, 1, 0),
    ("menu-materials", "材料管理", "", "/materials", "group-requirement", 1, 1, 0),
    ("menu-scores", "评分与冻结", "", "/scores", "group-requirement", 2, 1, 0),
    ("menu-zentao", "禅道集成", "", "/zentao", "group-requirement", 3, 1, 0),
    ("group-scenario", "场景", "🧩", "", "", 3, 1, 0),
    ("menu-lifecycle", "测试生命周期", "", "/lifecycle", "group-scenario", 0, 1, 0),
    ("menu-coverage", "覆盖缺口", "", "/coverage", "group-scenario", 1, 1, 0),
    ("menu-plans", "场景管理", "", "/plans", "group-scenario", 2, 1, 0),
    ("menu-dag", "DAG 编排", "", "/dag", "group-scenario", 3, 1, 0),
    ("group-agent", "Agent", "🤖", "", "", 4, 1, 0),
    ("menu-agent", "对话", "", "/agent", "group-agent", 0, 1, 0),
    ("menu-drafts", "草稿评审", "", "/drafts", "group-agent", 1, 1, 0),
    ("menu-skills", "技能", "", "/skills", "group-agent", 2, 1, 0),
    ("group-execution", "执行", "▶️", "", "", 5, 1, 0),
    ("menu-run", "测试执行", "", "/run", "group-execution", 0, 1, 0),
    ("menu-schedules", "定时任务", "", "/schedules", "group-execution", 1, 1, 0),
    ("menu-history", "执行记录", "", "/history", "group-execution", 2, 1, 0),
    ("menu-attribution", "失败归因", "", "/attribution", "group-execution", 3, 1, 0),
    ("group-feedback", "反哺", "🔄", "", "", 6, 1, 0),
    ("menu-feedback", "反哺闭环", "", "/feedback", "group-feedback", 0, 1, 0),
    ("menu-notify", "通知配置", "", "/notify", "group-feedback", 1, 1, 0),
]

SEED_ROLES: list[tuple] = [
    ("admin", "管理员", 0),
    ("tester", "测试", 1),
    ("viewer", "只读", 2),
    ("product", "产品", 3),
]

# 全新配置：仅 admin 保底两条（菜单管理 + 用户管理），其余零授权
SEED_ROLE_MENUS: list[tuple] = [
    ("admin", "menu-menu-manage"),
    ("admin", "menu-users"),
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path | None = None):
    """建表（幂等）+ 种子（表空时写入）。"""
    with _LOCK, _connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS menus (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_key   TEXT NOT NULL UNIQUE,
            label      TEXT NOT NULL,
            icon       TEXT NOT NULL DEFAULT '',
            path       TEXT NOT NULL DEFAULT '',
            parent_key TEXT NOT NULL DEFAULT '',
            sort       INTEGER NOT NULL DEFAULT 0,
            visible    INTEGER NOT NULL DEFAULT 1,
            is_system  INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS roles (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            role_key   TEXT NOT NULL UNIQUE,
            label      TEXT NOT NULL,
            is_builtin INTEGER NOT NULL DEFAULT 0,
            sort       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS role_menus (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            role_key TEXT NOT NULL,
            menu_key TEXT NOT NULL,
            UNIQUE (role_key, menu_key)
        );
        """)
        if conn.execute("SELECT COUNT(*) c FROM menus").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO menus (menu_key,label,icon,path,parent_key,sort,visible,is_system,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                [m + (_now(), _now()) for m in SEED_MENUS])
        if conn.execute("SELECT COUNT(*) c FROM roles").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO roles (role_key,label,is_builtin,sort,created_at) VALUES (?,?,?,?,?)",
                [(k, lb, 1, s, _now()) for k, lb, s in SEED_ROLES])
        if conn.execute("SELECT COUNT(*) c FROM role_menus").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO role_menus (role_key,menu_key) VALUES (?,?)", SEED_ROLE_MENUS)
        # 存量迁移（幂等）：首页让位给对话页，仪表盘改挂 /dashboard
        conn.execute(
            "UPDATE menus SET path='/dashboard', updated_at=? WHERE menu_key='menu-dashboard' AND path='/'",
            (_now(),))


def _ensure_audit(conn: sqlite3.Connection):
    conn.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        emp_no TEXT NOT NULL, action TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL)""")


def _audit(conn: sqlite3.Connection, emp_no: str, action: str, target: str, detail: str):
    _ensure_audit(conn)
    conn.execute(
        "INSERT INTO audit_log (emp_no,action,target,detail,created_at) VALUES (?,?,?,?,?)",
        (emp_no, action, target, detail, _now()))


def _row_menu(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in ("menu_key", "label", "icon", "path", "parent_key",
                                "sort", "visible", "is_system")} | {
        "is_public": row["menu_key"] in PUBLIC_MENUS,
    }


# ── 菜单 ──

def list_menus(db_path: Path | None = None) -> list[dict]:
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM menus ORDER BY sort, id").fetchall()
        return [_row_menu(r) for r in rows]


def get_menu(menu_key: str, db_path: Path | None = None) -> dict | None:
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM menus WHERE menu_key=?", (menu_key,)).fetchone()
        return _row_menu(row) if row else None


def create_menu(data: dict, db_path: Path | None = None):
    """新增菜单/分组。menu_key 规则 group-*/menu-*；parent_key 必须存在（分组为空串）。"""
    key = (data.get("menu_key") or "").strip()
    if not MENU_KEY_RE.match(key):
        raise ValueError("menu_key 需形如 group-xxx / menu-xxx（小写字母、数字、连字符）")
    parent = (data.get("parent_key") or "").strip()
    if parent and not get_menu(parent, db_path):
        raise ValueError(f"父分组不存在: {parent}")
    now = _now()
    with _LOCK, _connect(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO menus (menu_key,label,icon,path,parent_key,sort,visible,is_system,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (key, (data.get("label") or "").strip(), data.get("icon") or "",
                 data.get("path") or "", parent, int(data.get("sort") or 0),
                 1 if data.get("visible", True) else 0, 0, now, now))
        except sqlite3.IntegrityError:
            raise ValueError(f"menu_key 已存在: {key}")
        _audit(conn, key, "create_menu", key, (data.get("label") or "").strip())


def update_menu(menu_key: str, fields: dict, db_path: Path | None = None):
    """编辑 label/icon/path/parent_key/sort/visible。is_system 菜单禁止隐藏。"""
    menu = get_menu(menu_key, db_path)
    if not menu:
        raise ValueError(f"菜单不存在: {menu_key}")
    if menu["is_system"] and fields.get("visible") is False:
        raise ValueError("系统保护菜单不可隐藏")
    parent = (fields.get("parent_key") or menu["parent_key"]).strip()
    if parent and not get_menu(parent, db_path):
        raise ValueError(f"父分组不存在: {parent}")
    label = (fields.get("label") or menu["label"]).strip()
    now = _now()
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "UPDATE menus SET label=?, icon=?, path=?, parent_key=?, sort=?, visible=?, updated_at=?"
            " WHERE menu_key=?",
            (label, fields.get("icon", menu["icon"]), fields.get("path", menu["path"]),
             parent, int(fields.get("sort", menu["sort"])),
             1 if fields.get("visible", bool(menu["visible"])) else 0, now, menu_key))
        _audit(conn, menu_key, "update_menu", menu_key, label)


def delete_menu(menu_key: str, db_path: Path | None = None):
    """删除（有子项 / is_system 拒绝）；级联清除 role_menus 授权。"""
    menu = get_menu(menu_key, db_path)
    if not menu:
        return
    if menu["is_system"]:
        raise ValueError("系统保护菜单不可删除")
    with _LOCK, _connect(db_path) as conn:
        if conn.execute("SELECT 1 FROM menus WHERE parent_key=?", (menu_key,)).fetchone():
            raise ValueError("请先删除该分组下的子菜单")
        conn.execute("DELETE FROM menus WHERE menu_key=?", (menu_key,))
        conn.execute("DELETE FROM role_menus WHERE menu_key=?", (menu_key,))
        _audit(conn, menu_key, "delete_menu", menu_key, "")


# ── 角色 ──

def list_roles(db_path: Path | None = None) -> list[dict]:
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM roles ORDER BY sort, id").fetchall()
        return [{"role_key": r["role_key"], "label": r["label"],
                 "is_builtin": r["is_builtin"], "sort": r["sort"]} for r in rows]


def role_exists(role_key: str, db_path: Path | None = None) -> bool:
    try:
        with _LOCK, _connect(db_path) as conn:
            return conn.execute("SELECT 1 FROM roles WHERE role_key=?",
                                (role_key,)).fetchone() is not None
    except sqlite3.OperationalError:
        return False  # roles 表未建时按无自定义角色处理（内置白名单兜底）


def create_role(role_key: str, label: str, sort: int = 0, db_path: Path | None = None):
    key = (role_key or "").strip()
    if not ROLE_KEY_RE.match(key):
        raise ValueError("role_key 需小写字母开头（字母/数字/下划线/连字符，2-32 位）")
    if key in BUILTIN_ROLES:
        raise ValueError(f"role_key 与内置角色冲突: {key}")
    now = _now()
    with _LOCK, _connect(db_path) as conn:
        try:
            conn.execute("INSERT INTO roles (role_key,label,is_builtin,sort,created_at)"
                         " VALUES (?,?,0,?,?)", (key, (label or key).strip(), sort, now))
        except sqlite3.IntegrityError:
            raise ValueError(f"role_key 已存在: {key}")
        _audit(conn, key, "create_role", key, (label or key).strip())


def update_role(role_key: str, fields: dict, db_path: Path | None = None):
    if not role_exists(role_key, db_path):
        raise ValueError(f"角色不存在: {role_key}")
    label = (fields.get("label") or "").strip()
    sort = int(fields.get("sort") or 0)
    with _LOCK, _connect(db_path) as conn:
        conn.execute("UPDATE roles SET label=?, sort=? WHERE role_key=?",
                     (label, sort, role_key))
        _audit(conn, role_key, "update_role", role_key, label)


def delete_role(role_key: str, db_path: Path | None = None):
    """删除（内置 / 被用户引用拒绝）；级联清除授权。"""
    if not role_exists(role_key, db_path):
        return
    if role_key in BUILTIN_ROLES:
        raise ValueError("内置角色不可删除")
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE ','||roles||',' LIKE '%,'||?||',%'",
            (role_key,)).fetchone()
        if row["c"] > 0:
            raise ValueError(f"有 {row['c']} 名用户使用该角色，请先改绑")
        conn.execute("DELETE FROM roles WHERE role_key=?", (role_key,))
        conn.execute("DELETE FROM role_menus WHERE role_key=?", (role_key,))
        _audit(conn, role_key, "delete_role", role_key, "")


# ── 授权 ──

def list_role_menus(role_key: str, db_path: Path | None = None) -> list[str]:
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute("SELECT menu_key FROM role_menus WHERE role_key=? ORDER BY id",
                            (role_key,)).fetchall()
        return [r["menu_key"] for r in rows]


def set_role_menus(role_key: str, menu_keys: list[str], db_path: Path | None = None):
    """全量覆盖授权。强制约束：admin 与 SYSTEM_MENUS 的授权不可移除（自举保底）。"""
    keys = list(dict.fromkeys(menu_keys))  # 去重保序
    with _LOCK, _connect(db_path) as conn:
        if not conn.execute("SELECT 1 FROM roles WHERE role_key=?", (role_key,)).fetchone():
            raise ValueError(f"角色不存在: {role_key}")
        for k in keys:
            if not conn.execute("SELECT 1 FROM menus WHERE menu_key=?", (k,)).fetchone():
                raise ValueError(f"菜单不存在: {k}")
        if role_key == "admin":
            keys = list(dict.fromkeys(keys + list(SYSTEM_MENUS)))
        conn.execute("DELETE FROM role_menus WHERE role_key=?", (role_key,))
        conn.executemany("INSERT INTO role_menus (role_key,menu_key) VALUES (?,?)",
                         [(role_key, k) for k in keys])
        _audit(conn, role_key, "set_role_menus", role_key, ",".join(keys))


def user_has_menu(role_keys: list[str], menu_key: str, db_path: Path | None = None) -> bool:
    """守卫用：角色集任一授权即通过；admin 对 is_system 菜单恒通过（双保险）；
    公开菜单（PUBLIC_MENUS）登录即放行（无需任何授权）。"""
    if menu_key in PUBLIC_MENUS:
        return True
    if not role_keys:
        return False
    if "admin" in role_keys:
        menu = get_menu(menu_key, db_path)
        if menu and menu["is_system"]:
            return True
    ph = ",".join("?" * len(role_keys))
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            f"SELECT 1 FROM role_menus WHERE menu_key=? AND role_key IN ({ph})",
            (menu_key, *role_keys)).fetchone()
        return row is not None


def menus_for_user(role_keys: list[str], db_path: Path | None = None) -> list[dict]:
    """当前用户可见菜单树（侧边栏渲染）：授权并集 ∪ 公开菜单 ∩ visible=1，分组无可见子项不返回。

    授权针对菜单项（分组本身不参与授权）；分组只要有被授权的可见子项即显示。
    返回 [{"label","icon","items":[{"to","label","end"}]}]，单子项分组仍为 group（前端现有逻辑处理）。
    """
    all_menus = {m["menu_key"]: m for m in list_menus(db_path)}
    visible_keys = {k for k, m in all_menus.items() if m["visible"]}
    granted = {k for k in visible_keys if user_has_menu(role_keys, k, db_path)}
    # 分组节点：其下有被授权子项即显示（分组本身无需授权）
    parent_keys = {m["parent_key"] for m in all_menus.values() if m["menu_key"] in granted}
    group_keys = {k for k in parent_keys if k and k in all_menus and all_menus[k]["visible"]}
    out = []
    for g in sorted((all_menus[k] for k in group_keys), key=lambda m: m["sort"]):
        items = [m for m in all_menus.values()
                 if m["menu_key"] in granted and m["parent_key"] == g["menu_key"]]
        if not items:
            continue
        out.append({
            "label": g["label"],
            "icon": g["icon"],
            "items": [{"to": m["path"] or "/", "label": m["label"],
                       "end": m["path"] == "/"} for m in sorted(items, key=lambda m: m["sort"])],
        })
    return out
