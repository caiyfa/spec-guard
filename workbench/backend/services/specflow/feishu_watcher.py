"""feishu_watcher.py — 飞书事件监听托管器（飞书知识图谱二期 F1，T-917~T-919）。

架构：workbench 后端 startup 拉起（复刻 scheduler 进程内托管先例），
3 路 lark-cli event consume 子进程（IM bot / minutes user / vc user）。

单用户守卫（二期边界）：.lark-cli/{emp} × feishu_watch.yaml × token 有效，
恰好 1 人才启动（0 静默 / >1 告警不启动）；多用户编排三期再议。

子进程纪律（lark-event 契约）：
- stdin=PIPE 保活（unbounded run 下 stdin EOF 即优雅退出——stop 先关 stdin）
- stderr 阻塞等 `[event] ready event_key=` 就绪标记，再读 stdout
- 禁 kill -9（minutes/vc 退出时 OAPI 退订，强杀泄漏服务端订阅）
- 非零退出 → 指数退避重启；连续 5 次崩溃 → 停摆 ERROR 告警（不静默自愈）

事件→材料转化（D1）：事件只作触发器——节流合并后调一期 sync 服务重拉落池，
材料池格式与手动同步完全一致（单一代码路径）。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

EVENT_KEYS = [
    ("im.message.receive_v1", "bot"),
    ("minutes.minute.generated_v1", "user"),
    ("vc.note.generated_v1", "user"),
]

THROTTLE_SECONDS = 300        # 5min 滑动窗口（测试可 patch）
BACKOFF_BASE = 1.0            # 指数退避基数（秒）
BACKOFF_MAX = 300.0
MAX_CONSEC_CRASH = 5
READY_TIMEOUT = 20            # stderr ready 等待上限（秒）


# ══════════════════════════════════════════════════════════
# 单用户守卫
# ══════════════════════════════════════════════════════════

def _token_valid(sg_root: Path, emp: str) -> bool:
    """lark-cli auth status（USERPROFILE 注入该用户配置目录），ready 即有效。"""
    env = dict(os.environ)
    env["USERPROFILE"] = str(Path(sg_root) / ".lark-cli" / emp)
    cmd = (["cmd", "/c", "lark-cli"] if sys.platform == "win32" else ["lark-cli"])
    try:
        proc = subprocess.run(
            cmd + ["auth", "status", "--format", "json"],
            capture_output=True, text=True, timeout=15, env=env,
            encoding="utf-8", errors="replace")
        return '"ready"' in (proc.stdout or "")
    except Exception:
        return False


def resolve_watch_user(sg_root: Path) -> str | None:
    """单用户守卫：恰好 1 个「watch 配置 + token 有效」用户 → emp_no；否则 None。"""
    root = Path(sg_root)
    lark_root = root / ".lark-cli"
    if not lark_root.is_dir():
        return None
    cands = []
    for d in sorted(lark_root.iterdir()):
        if not d.is_dir():
            continue
        if (root / ".specflow" / d.name / "feishu_watch.yaml").is_file():
            cands.append(d.name)
    valid = [e for e in cands if _token_valid(root, e)]
    if len(valid) > 1:
        log.warning("feishu_watcher: %d 个用户满足监听条件，二期单用户边界——不启动",
                    len(valid))
        return None
    return valid[0] if valid else None


# ══════════════════════════════════════════════════════════
# 托管器
# ══════════════════════════════════════════════════════════

def resolve_material_base() -> Path | None:
    """T-949 共享材料区根（激活工作区时 {ws}/.specflow/；无上下文回退 None=私有区）。

    工作台进程内必然有激活工作区；独立 CLI/测试场景无注册表 → None，
    调用方回退各 emp 私有区（向后兼容单用户模式）。
    """
    try:
        from specstd.workspace import specflow_dir
        return specflow_dir("")
    except Exception:
        return None


def chat_sync_job(emp_base_str: str):
    """T-952：可配置定时同步 job（模块级——APScheduler 需可序列化 callable）。

    watch 配置 chat_sync_minutes>0 时由 _schedule_chat_sync 注册 interval 触发；
    全通道拉取（含自动聚类/转述）落共享材料区。
    """
    from services.specflow import feishu_sync_service as svc
    try:
        svc.sync_all(Path(emp_base_str),
                     material_base=resolve_material_base())
    except Exception as e:
        log.warning("定时同步失败 %s: %s", emp_base_str, e)


def chat_proofread_job(emp_base_str: str):
    """每日群聊校对重拉 job（模块级——APScheduler 需可序列化 callable，禁闭包）。

    T-949：重拉落共享材料区（resolve_material_base；无工作区上下文回退私有区）。
    """
    from services.specflow import feishu_sync_service as svc
    emp_base = Path(emp_base_str)
    cfg = svc.load_watch_config(emp_base)
    material_base = resolve_material_base()
    day = datetime.now().strftime("%Y%m%d")
    for chat in cfg.get("chats") or []:
        try:
            svc.sync_chat(material_base or emp_base,
                          str(chat.get("chat_id", "")), day)
        except Exception as ce:
            log.warning("校对重拉失败 %s: %s", chat.get("chat_id"), ce)
    # T-945：校对落池后异步聚类（候选话题次晨更新，演进链对齐飞书侧全量）
    svc.maybe_cluster_async(emp_base, material_base=material_base)


def user_materials_job(emp_base_str: str):
    """每日用户材料轮询 job（模块级——APScheduler 需可序列化 callable，禁闭包）。"""
    from services.specflow import feishu_sync_service as svc
    out = svc.sync_user_materials(Path(emp_base_str))
    if out.get("errors"):
        log.warning("用户材料轮询部分失败: %s", out["errors"])


def chats_warmup_job(emp: str):
    """群聊列表缓存预热 job（T-938，模块级——可序列化铁律）。

    同步设置弹层打开即命中缓存秒出；emp 透传 list_my_chats 身份隔离
    （USERPROFILE=.lark-cli/{emp}，与 _spawn/_token_valid 同约定）。
    失败仅 log.warning（errors 通道），不炸 scheduler 线程。
    """
    from services.specflow import feishu_sync_service as svc
    out = svc.list_my_chats(emp=emp)
    if out.get("errors"):
        log.warning("群聊列表预热失败 emp=%s: %s", emp, out["errors"])


class FeishuWatcher:
    def __init__(self, sg_root: Path):
        self.sg_root = Path(sg_root)
        self.emp: str | None = None
        self._procs: list = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._last_pull: dict[str, float] = {}
        self._started_at = ""
        self._events_received = 0
        self._last_event_at = ""

    # ── 生命周期 ──

    def start(self, emp: str = "") -> bool:
        """启动监听（emp 指定用户；空则走守卫解析；不满足 → False）。"""
        self.emp = emp or resolve_watch_user(self.sg_root)
        if not self.emp:
            return False
        self._stop.clear()
        self._started_at = datetime.now().isoformat(timespec="seconds")
        self._catch_up()
        self._schedule_doc_poll()
        self._schedule_chat_sync()
        self._schedule_chat_proofread()
        self._schedule_user_materials()
        self._schedule_chats_warmup()
        for key, identity in EVENT_KEYS:
            self._launch(key, identity)
        log.info("feishu_watcher 已启动（emp=%s，%d 路事件）", self.emp, len(EVENT_KEYS))
        return True

    def _schedule_doc_poll(self):
        """T-922：文档日级轮询 job（APScheduler 直接挂，不落 jobs 表——表属 plan 语义）。"""
        try:
            from services.scheduler import get_scheduler
            from services.specflow import feishu_sync_service as svc
            emp_base = self.sg_root / ".specflow" / self.emp
            get_scheduler().add_job(
                svc.sync_recent_docs, args=[emp_base], kwargs={"days": 1},
                trigger="cron", hour=7, minute=0,
                id=f"feishu-docs-{self.emp}", replace_existing=True)
        except Exception as e:
            log.warning("feishu_watcher 文档轮询 job 挂载失败（不阻断监听）: %s", e)

    def _schedule_chat_sync(self):
        """T-952：可配置定时同步（watch.chat_sync_minutes>0 时 interval 触发；
        0/未配置=不挂载，保持每日校对克频）。保存配置即重启监听时重新挂载。"""
        try:
            from services.scheduler import get_scheduler
            emp_base = self.sg_root / ".specflow" / self.emp
            from services.specflow import feishu_sync_service as svc
            minutes = int(svc.load_watch_config(emp_base)
                          .get("chat_sync_minutes") or 0)
            if minutes > 0:
                get_scheduler().add_job(
                    chat_sync_job, args=[str(emp_base)],
                    trigger="interval", minutes=minutes,
                    id=f"feishu-chat-sync-{self.emp}", replace_existing=True)
            else:
                try:
                    get_scheduler().remove_job(f"feishu-chat-sync-{self.emp}")
                except Exception:
                    pass                      # 未挂载过，无事
        except Exception as e:
            log.warning("feishu_watcher 定时同步 job 挂载失败（不阻断监听）: %s", e)

    def _schedule_chat_proofread(self):
        """T-925：每日 03:00 群聊校对重拉（覆盖写——撤回/编辑/直写丢漏对齐飞书侧）。

        job callable 必须模块级（APScheduler 序列化限制）——闭包会炸 startup。
        """
        try:
            from services.scheduler import get_scheduler
            emp_base = self.sg_root / ".specflow" / self.emp
            get_scheduler().add_job(
                chat_proofread_job, args=[str(emp_base)],
                trigger="cron", hour=3, minute=0,
                id=f"feishu-proofread-{self.emp}", replace_existing=True)
        except Exception as e:
            log.warning("feishu_watcher 校对 job 挂载失败（不阻断监听）: %s", e)

    def _schedule_user_materials(self):
        """每日 08:00 用户材料轮询（错开 07:00 文档轮询 / 03:00 群聊校对）。

        job callable 必须模块级（APScheduler 序列化限制）——闭包会炸 startup。
        """
        try:
            from services.scheduler import get_scheduler
            emp_base = self.sg_root / ".specflow" / self.emp
            get_scheduler().add_job(
                user_materials_job, args=[str(emp_base)],
                trigger="cron", hour=8, minute=0,
                id=f"feishu-user-materials-{self.emp}", replace_existing=True)
        except Exception as e:
            log.warning("feishu_watcher 用户材料轮询 job 挂载失败（不阻断监听）: %s", e)

    def _schedule_chats_warmup(self):
        """T-938：群聊列表缓存预热（interval 5min；next_run_time=now 启动即首跑）。

        同步设置弹层打开即命中缓存秒出（stale-while-revalidate 兑底：
        预热间隙打开返旧值 + 后台刷新）。job callable 模块级（序列化铁律）。
        """
        try:
            from services.scheduler import get_scheduler
            get_scheduler().add_job(
                chats_warmup_job, args=[self.emp],
                trigger="interval", minutes=5, next_run_time=datetime.now(),
                id=f"feishu-chats-warmup-{self.emp}", replace_existing=True)
        except Exception as e:
            log.warning("feishu_watcher 群聊预热 job 挂载失败（不阻断监听）: %s", e)

    def stop(self):
        """优雅停：先关 stdin（EOF 触发优雅退出），10s 超时再 terminate。禁 kill。"""
        self._stop.set()
        for proc in self._procs:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
        deadline = time.time() + 10
        for proc in self._procs:
            try:
                proc.wait(timeout=max(0.1, deadline - time.time()))
            except Exception:
                with contextlib.suppress(Exception):
                    proc.terminate()

    def stats(self) -> dict:
        """运行状态（T-924 注册表/T-929 状态端点用）。"""
        return {"started_at": self._started_at,
                "events_received": self._events_received,
                "last_event_at": self._last_event_at}

    def _catch_up(self):
        """启动 catch-up：全量补拉一次（补离线窗口；幂等覆盖写）。"""
        try:
            from services.specflow import feishu_sync_service as svc
            svc.sync_all(self.sg_root / ".specflow" / self.emp,
                         material_base=resolve_material_base())
        except Exception as e:
            log.warning("feishu_watcher catch-up 失败（不阻断监听）: %s", e)

    # ── 子进程托管 ──

    def _launch(self, event_key: str, identity: str):
        t = threading.Thread(target=self._supervise, args=(event_key, identity),
                             daemon=True, name=f"feishu-watch-{event_key}")
        t.start()
        self._threads.append(t)

    def _spawn(self, event_key: str, identity: str):
        """拉起 consume 子进程（USERPROFILE 注入该用户配置；stdin=PIPE 保活）。"""
        env = dict(os.environ)
        env["USERPROFILE"] = str(self.sg_root / ".lark-cli" / self.emp)
        cmd = (["cmd", "/c", "lark-cli"] if sys.platform == "win32" else ["lark-cli"])
        return subprocess.Popen(
            cmd + ["event", "consume", event_key, "--as", identity],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", env=env)

    def _supervise(self, event_key: str, identity: str):
        backoff = BACKOFF_BASE
        crashes = 0
        while not self._stop.is_set():
            try:
                proc = self._spawn(event_key, identity)
            except Exception as e:
                log.error("feishu_watcher %s 拉起失败: %s", event_key, e)
                return
            self._procs.append(proc)
            if not self._wait_ready(proc, event_key):
                proc.wait()
                crashes += 1
                if crashes >= MAX_CONSEC_CRASH:
                    log.error("feishu_watcher %s 连续崩溃 %d 次，停摆告警",
                              event_key, crashes)
                    return
                time.sleep(min(backoff, BACKOFF_MAX))
                backoff *= 2
                continue
            crashes = 0
            backoff = BACKOFF_BASE
            self._consume(proc, event_key)
            rc = proc.wait()
            if self._stop.is_set():
                break
            log.warning("feishu_watcher %s 退出 rc=%s，退避重启", event_key, rc)
            time.sleep(min(backoff, BACKOFF_MAX))
            backoff *= 2

    def _wait_ready(self, proc, event_key: str) -> bool:
        """阻塞读 stderr 至 [event] ready（超时 READY_TIMEOUT 判失败）。"""
        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline and not self._stop.is_set():
            line = proc.stderr.readline()
            if f"[event] ready event_key={event_key}" in line:
                return True
            if line == "" and proc.poll() is not None:
                return False
        return False

    def _consume(self, proc, event_key: str):
        for line in proc.stdout:
            if self._stop.is_set():
                return
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._on_event(event_key, ev)

    # ── 事件 → 节流 → 重拉 ──

    def _on_event(self, event_key: str, ev: dict):
        self._events_received += 1
        self._last_event_at = datetime.now().isoformat(timespec="seconds")
        if event_key == "im.message.receive_v1":
            self._direct_write_chat(ev)          # T-925：IM 直写（秒级）
        elif event_key in ("minutes.minute.generated_v1", "vc.note.generated_v1"):
            token = ev.get("minute_token") or ev.get("note_token") or ""
            if token:
                self._throttled(f"minutes:{token}", kind="minutes", token=token)

    def _direct_write_chat(self, ev: dict):
        """IM 事件直写（T-925 建立；T-948 改 JSONL 事实源 + md 视图重建）。
    
        事件无 message_id → "evt:{event_id}" 幂等键（与拉取键不冲突）；
        每日校对重拉以拉取结果为权威（同消息 pull 版本覆盖吸收 evt 条目）。
        授权校验 + 发送人过滤（设计 D4/D5）：仅授权 chat 且（配置了
        group_sender 时）命中发送人的消息才直写；校对重拉全量不受过滤影响。
        """
        from specflow.feishu_pool import chat_store, pool_store
        from specflow.feishu_pool.paths import pool_dirs
        event_id = str(ev.get("event_id") or "")
        chat_id = str(ev.get("chat_id") or "")
        if not chat_id:
            return
        emp_base = self.sg_root / ".specflow" / self.emp
        if not self._authorized_for_direct_write(
                emp_base, chat_id, str(ev.get("sender_id") or "")):
            return
        if event_id and not pool_store.mark_event_seen(emp_base, event_id):
            return                              # 重复事件不双写
        ms = int(ev.get("create_time") or 0)
        ts = datetime.fromtimestamp(ms / 1000) if ms else datetime.now()
        sender = pool_store.sender_display(emp_base, str(ev.get("sender_id") or ""))
        row = chat_store.normalize_event_message({**ev, "sender_name": sender})
        cs8 = pool_store.chat_sha8(chat_id)
        day = ts.strftime("%Y%m%d")
        # T-949：直写落共享材料区（event_id 去重表仍留私有区——每用户自己的事件流）
        material_root = resolve_material_base() or emp_base
        day_file = pool_dirs(material_root)["chats"] / cs8 / f"{day}.jsonl"
        chat_store.merge_chat_jsonl(day_file, [row])
        chat_store.rebuild_views(day_file)

    def _authorized_for_direct_write(self, emp_base: Path, chat_id: str,
                                     sender_id: str) -> bool:
        """直写授权校验（配置即时读取，保存即生效，无需重启子进程——D1）。

        1. chat_id 须在 watch.chats 授权清单内（D5：兑现同步范围即授权范围；
           p2p 事件 chat_id 天然不在清单，兼容 D2 私聊不做）；
        2. G = scopes 含 group_sender 的 users open_id 集合——G 非空时
           sender_id 须 ∈ G（D4：仅直写过滤，校对全量覆盖）。
        配置读取异常 → 放行并 warning（不打断事件循环，校对重拉兜底）。
        """
        try:
            from services.specflow import feishu_sync_service as svc
            cfg = svc.load_watch_config(emp_base)
        except Exception as e:
            log.warning("feishu_watcher 读 watch 配置失败，放行直写: %s", e)
            return True
        authorized = {str(c.get("chat_id", "")) for c in cfg.get("chats") or []}
        if chat_id not in authorized:
            return False
        senders = {str(u.get("open_id", "")) for u in cfg.get("users") or []
                   if "group_sender" in (u.get("scopes") or [])}
        if senders and sender_id not in senders:
            return False
        return True

    def _throttled(self, key: str, **pull_kw):
        now = time.time()
        if now - self._last_pull.get(key, 0) < THROTTLE_SECONDS:
            return
        self._last_pull[key] = now
        self._trigger_pull(**pull_kw)

    def _trigger_pull(self, kind: str, **kw):
        """重拉（复用一期 sync 服务，单一代码路径）。"""
        from services.specflow import feishu_sync_service as svc
        emp_base = self.sg_root / ".specflow" / self.emp
        try:
            if kind == "chat":
                svc.sync_chat(emp_base, kw["chat_id"],
                              datetime.now().strftime("%Y%m%d"))
            elif kind == "minutes":
                svc.sync_minutes(emp_base, days=3)
        except Exception as e:
            log.warning("feishu_watcher 重拉失败 %s: %s", kw, e)


def resolve_watch_users(sg_root: Path) -> list[str]:
    """多用户枚举（T-924）：全部「watch 配置 + token 有效」用户的 emp_no 列表。"""
    root = Path(sg_root)
    lark_root = root / ".lark-cli"
    if not lark_root.is_dir():
        return []
    cands = []
    for d in sorted(lark_root.iterdir()):
        if not d.is_dir():
            continue
        if (root / ".specflow" / d.name / "feishu_watch.yaml").is_file():
            cands.append(d.name)
    return [e for e in cands if _token_valid(root, e)]


# ══════════════════════════════════════════════════════════
# 多用户注册表（三期 T-924）
# ══════════════════════════════════════════════════════════

MAX_WATCHERS = 50   # 软上限：超出 WARN 拒绝新启动


class WatcherRegistry:
    """多用户监听注册表：{emp: FeishuWatcher} + 配置驱动启停 + 状态落盘。"""

    def __init__(self, sg_root: Path):
        self.sg_root = Path(sg_root)
        self.watchers: dict[str, FeishuWatcher] = {}

    def start_all(self) -> list[str]:
        """启动全部满足条件的用户（软上限内），返回成功启动的 emp 列表。"""
        started = []
        for emp in resolve_watch_users(self.sg_root):
            if len(self.watchers) >= MAX_WATCHERS:
                log.warning("feishu_watcher 达软上限 %d，跳过 %s", MAX_WATCHERS, emp)
                break
            if self.start_user(emp):
                started.append(emp)
        return started

    def start_user(self, emp: str) -> bool:
        """启动单用户监听（幂等：已在跑跳过）。"""
        if emp in self.watchers:
            return False
        if len(self.watchers) >= MAX_WATCHERS:
            log.warning("feishu_watcher 达软上限 %d，拒绝启动 %s", MAX_WATCHERS, emp)
            return False
        w = FeishuWatcher(self.sg_root)
        if not w.start(emp=emp):
            return False
        self.watchers[emp] = w
        return True

    def stop_user(self, emp: str) -> bool:
        """停止单用户监听（幂等：未在跑跳过）。"""
        w = self.watchers.pop(emp, None)
        if w is None:
            return False
        w.stop()
        return True

    def stop_all(self):
        for emp in list(self.watchers):
            self.stop_user(emp)

    def status(self) -> dict:
        """内存状态快照（事件计数等取自各 watcher.stats）。"""
        return {"count": len(self.watchers),
                "watchers": [{"emp": emp, **w.stats()} for emp, w
                             in sorted(self.watchers.items())]}

    def persist_status(self, workspace_root: Path) -> Path:
        """状态落盘 {ws}/.specguard/feishu/watchers.json（管理可查）。"""
        path = Path(workspace_root) / ".specguard" / "feishu" / "watchers.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.status(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path


# ══════════════════════════════════════════════════════════
# 模块级单例（main.py startup/shutdown 接线用；三期起走注册表）
# ══════════════════════════════════════════════════════════

_REGISTRY: WatcherRegistry | None = None


def start_background(sg_root: Path) -> bool:
    """启动全局注册表并拉起全部满足条件的用户（幂等）。

    注册表常驻创建（无满足用户时为空注册表）——后续 PUT watch 配置
    可经 get_registry().start_user(emp) 动态拉起（T-924 配置驱动启停）。
    Returns: 是否有 watcher 被启动（注册表本身总是就绪）。
    """
    global _REGISTRY
    if _REGISTRY is not None:
        return False
    reg = WatcherRegistry(sg_root)
    started = reg.start_all()
    _REGISTRY = reg
    return bool(started)


def stop_background():
    """停止全局注册表（幂等）。"""
    global _REGISTRY
    if _REGISTRY is None:
        return
    try:
        _REGISTRY.stop_all()
    finally:
        _REGISTRY = None


def get_registry() -> WatcherRegistry | None:
    """取全局注册表（watcher-status 端点用；未启动返回 None）。"""
    return _REGISTRY
