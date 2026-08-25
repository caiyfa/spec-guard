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
PUBLIC_MENUS = ("menu-agent", "menu-db-console")
# 内置角色：不可删、key 不可改
BUILTIN_ROLES = ("admin", "tester", "viewer", "product")
ROLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
MENU_KEY_RE = re.compile(r"^(group|menu)-[a-z0-9-]{1,63}$")

# ── 种子数据：菜单树（T-996 信息架构收缩：8 组 29 叶 → 5 组 16 叶；全新配置 = 零角色授权）──
# (menu_key, label, icon, path, parent_key, sort, visible, is_system)
# 血缘链并入全景图谱第四镜头；技能/材料/评分/禅道/合规收进 Agent 对话页内页签；
# 覆盖缺口并入生命周期页；定时任务/失败归因并入执行中心；通知配置并入反哺闭环。
SEED_MENUS: list[tuple] = [
    ("group-overview", "总览", "📊", "", "", 0, 1, 0),
    ("menu-dashboard", "仪表盘", "", "/dashboard", "group-overview", 0, 1, 0),
    ("menu-graph", "全景图谱", "", "/graph", "group-overview", 1, 1, 0),
    ("menu-activity", "我的活动", "", "/my-activity", "group-overview", 2, 1, 0),
    ("group-agent", "Agent", "🤖", "", "", 1, 1, 0),
    ("menu-agent", "Agent 对话", "", "/agent", "group-agent", 0, 1, 0),
    ("menu-drafts", "草稿评审", "", "/drafts", "group-agent", 1, 1, 0),
    ("group-scenario", "场景", "🧩", "", "", 2, 1, 0),
    ("menu-plans", "场景管理", "", "/plans", "group-scenario", 0, 1, 0),
    ("menu-dag", "DAG 编排", "", "/dag", "group-scenario", 1, 1, 0),
    ("menu-feishu-pool", "飞书话题", "", "/feishu-pool", "group-scenario", 2, 1, 0),   # T-1003：原「飞书材料池」改名（种子 label 每次启动同步存量 menus 表，见 _migrate_menus_t996 UPDATE 分支）
    ("menu-lifecycle", "覆盖与生命周期", "", "/lifecycle", "group-scenario", 3, 1, 0),
    ("group-execution", "执行", "▶️", "", "", 3, 1, 0),
    ("menu-run", "测试执行", "", "/run", "group-execution", 0, 1, 0),
    ("menu-history", "执行中心", "", "/history", "group-execution", 1, 1, 0),
    ("menu-feedback", "反哺闭环", "", "/feedback", "group-execution", 2, 1, 0),
    ("menu-db-console", "DB 证据", "🗄", "/db-console", "group-execution", 3, 1, 0),
    ("group-system", "系统管理", "⚙️", "", "", 4, 1, 0),
    ("menu-users", "用户管理", "", "/admin-users", "group-system", 0, 1, 1),
    ("menu-menu-manage", "菜单管理", "", "/menu-roles", "group-system", 1, 1, 1),
    ("menu-audit", "审计日志", "", "/audit", "group-system", 2, 1, 0),
    ("menu-system-config", "系统配置", "", "/system-config", "group-system", 3, 1, 0),  # T-1010：系统包+工作区+环境配置三栏合一
    ("menu-settings", "基础设置", "", "/settings", "group-system", 4, 1, 0),  # T-1010：原「系统设置」（数据库 tab 已并入系统配置）
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
        _migrate_menus_t996(conn)


# T-996 信息架构收缩：已移除的菜单键 → 幸存菜单键（授权无损映射）
_MENU_REMAP_T996: dict[str, str] = {
    "menu-lineage": "menu-graph",       # 血缘链并入全景图谱第四镜头
    "menu-coverage": "menu-lifecycle",  # 覆盖缺口并入生命周期页（两 tab）
    "menu-schedules": "menu-history",   # 定时任务并入执行中心
    "menu-attribution": "menu-history", # 失败归因并入执行中心
    "menu-notify": "menu-feedback",     # 通知配置并入反哺闭环
    "menu-skills": "menu-agent",        # 技能收对话只读页签
    "menu-materials": "menu-agent",     # 材料管理收操作台页签
    "menu-scores": "menu-agent",        # 评分冻结收操作台页签
    "menu-zentao": "menu-agent",        # 禅道集成收对话页内
    "menu-spec": "menu-agent",          # 合规校验收对话页内
    "menu-knowledge": "menu-agent",     # 知识收对话页内
    "menu-quality": "menu-dashboard",   # 质量中心（死菜单，/quality 无路由）
    # T-1010「系统配置」三栏合一：系统包管理/环境配置/工作区中心全部收编（授权无损映射）
    "menu-workspace": "menu-system-config",    # 工作区中心并入系统配置中栏
    "menu-env-config": "menu-system-config",   # 环境配置并入系统配置右栏
    "menu-systems": "menu-system-config",      # 系统包管理并入系统配置左栏
}
# T-996 移除的分组（子项已全部迁出）
_GROUPS_REMOVED_T996 = ("group-workspace", "group-requirement", "group-feedback", "group-quality")


def _migrate_menus_t996(conn: sqlite3.Connection):
    """菜单信息架构收缩迁移（幂等）：

    1) upsert 新种子树（INSERT OR IGNORE + 对齐 label/path/parent_key/sort/is_system，
       visible 不动——管理员手工隐藏的保持隐藏）；
    2) 存量授权按 _MENU_REMAP_T996 无损映射到幸存菜单（INSERT OR IGNORE 防唯一冲突）；
    3) 删除已移除的菜单/分组行及其授权残留。
    检测条件：旧键一个都不存在时跳过 2/3（全新库直接走种子）。
    """
    now = _now()
    for m in SEED_MENUS:
        conn.execute(
            "INSERT OR IGNORE INTO menus (menu_key,label,icon,path,parent_key,sort,visible,is_system,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", m + (now, now))
        conn.execute(
            "UPDATE menus SET label=?, icon=?, path=?, parent_key=?, sort=?, is_system=?, updated_at=?"
            " WHERE menu_key=? AND (label!=? OR icon!=? OR path!=? OR parent_key!=? OR sort!=? OR is_system!=?)",
            (m[1], m[2], m[3], m[4], m[5], m[7], now, m[0], m[1], m[2], m[3], m[4], m[5], m[7]))
    old_keys = list(_MENU_REMAP_T996) + list(_GROUPS_REMOVED_T996)
    ph = ",".join("?" * len(old_keys))
    if not conn.execute(f"SELECT 1 FROM menus WHERE menu_key IN ({ph}) LIMIT 1", old_keys).fetchone():
        return
    rows = conn.execute(
        f"SELECT role_key, menu_key FROM role_menus WHERE menu_key IN ({ph})", old_keys).fetchall()
    for r in rows:
        target = _MENU_REMAP_T996.get(r["menu_key"])
        if target:
            conn.execute("INSERT OR IGNORE INTO role_menus (role_key,menu_key) VALUES (?,?)",
                         (r["role_key"], target))
    conn.execute(f"DELETE FROM role_menus WHERE menu_key IN ({ph})", old_keys)
    conn.execute(f"DELETE FROM menus WHERE menu_key IN ({ph})", old_keys)


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
