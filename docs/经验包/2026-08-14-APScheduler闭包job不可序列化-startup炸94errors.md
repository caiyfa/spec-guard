# APScheduler 闭包 job 不可序列化 → TestClient 全量 startup 炸 94 errors

## 现象

飞书知识图谱三期 T-925（每日校对重拉 job）提交后，全量回归 `python -m pytest test_specstd test_engine` 出现 **94 errors + 1 failed**，集中在 TestClient 类测试（test_gate_dock 等）的 setup 阶段：

```
ValueError: This Job cannot be serialized since the reference to its callable
(<function FeishuWatcher._schedule_chat_proofread.<locals>_job ...>) could not be determined.
Consider giving a textual reference (module:function name) instead.
```

## 证据链

- 报错堆栈指向 `apscheduler/job.py:263` 的序列化校验；
- 触发链：TestClient startup → main.py `_startup()` → `feishu_watcher.start_background(SG_ROOT)` → watcher 启动 → `_schedule_chat_proofread` 挂 job → APScheduler 序列化 callable → 闭包引用不可判定 → ValueError；
- 闭包函数定义于 `_schedule_chat_proofread` 方法体内（`<locals>` 路径），模块级不可导入。

## 根因（哪个环节缺失）

**实现层**：给 APScheduler `add_job` 传了**方法内闭包**作为 callable。APScheduler 的 jobstore/序列化校验要求 callable 是可导入的模块级引用（`module:function`），闭包/lambda 无法序列化。单元测试（watcher 直测）不经过 TestClient startup 所以未暴露；全量回归经 TestClient 才触发。

## 修复

`chat_proofread_job(emp_base_str: str)` 提升为 `feishu_watcher.py` **模块级函数**（参数从闭包捕获改为显式传字符串路径），`add_job(chat_proofread_job, args=[str(emp_base)], ...)`。commit 683e559（随 T-928 收口笔）。修复后全量 1618 passed。

对照：二期 `_schedule_doc_poll` 传的是 `svc.sync_recent_docs`（模块级函数）所以没炸——同文件两种写法，闭包是三期新引入的变异。

## 预防（可执行检查清单）

- [ ] **给 APScheduler add_job 传 callable 时，必须是模块级可导入函数**（禁闭包/lambda/实例方法）；参数走 args/kwargs 显式传，不靠闭包捕获
- [ ] 新增 startup 期挂载的后台任务后，必跑**全量回归**（单测绿不代表 startup 安全——TestClient 会拉起真实 startup 链）
- [ ] 排障动线：大量 TestClient 测试 setup 阶段集体报错 → 先查 startup 事件链（main.py `_startup` 挂载的组件）
