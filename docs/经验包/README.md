# 问题修复经验包

> SpecGuard 排障闭环的知识沉淀：每个「具体问题 → 根因 → 修复 → 预防」独立一文件，
> 本 README 是**入口与协议**（AGENTS.md 指向此处）。
> 建立：2026-08-02 ｜ 首个案例：EX-8200eada（变量未定义 · 权限缺失）

---

## 协议（排障闭环后登记）

1. **命名**：`{日期}-{任务号}-{现象摘要}.md`（如 `2026-08-02-EX-8200eada-变量未定义-权限缺失.md`）
2. **模板**：每个经验包固定五段——
   - **现象**：任务号 / 错误消息 / 用户看到的表象
   - **证据链**：output.log / run.json / 响应体 / 失败索引 等关键摘录（附位置）
   - **根因**：哪个环节缺失（环境 / 场景 / 引擎 / 配置），一句话结论
   - **修复**：代码 / 场景 / 环境动作（附提交号）
   - **预防**：检查清单 / 约定 / 相关任务号
3. **登记**：新增经验包后，在本 README 索引表追加一行，并在 AGENTS.md「问题修复经验包」入口章节确认指向不变（入口永远指向本 README）
4. **原则**：写「可复现的事实」不写推测；根因必须是证据链支持的结论；预防要可执行

## 索引

| 日期 | 任务号 | 现象 | 根因（环节） | 修复 | 预防 |
|---|---|---|---|---|---|
| 2026-08-02 | [EX-8200eada](2026-08-02-EX-8200eada-变量未定义-权限缺失.md) | `变量未定义: activity.json.data.id` | SIT 权限体系 TDM_INV_ACTIVITY 资源码无绑定账号（环境） | 写型场景首步补 precheck_permission（2d969c4）；SIT 授权待环境侧 | 写型场景首步 precheck；环境交付 checklist 绑定写型资源码 |
| 2026-08-02 | [测试污染生产配置](2026-08-02-测试污染生产配置-monkeypatch双实例陷阱.md) | env.sit.yaml 被测试覆盖截断 | monkeypatch 双模块实例（sys.path 双路径导入，测试基建） | 同实例导入修复 + git checkout 恢复（4be2aee 前后） | 写盘测试验证模块同实例；跑完查 git status |
| 2026-08-12 | [pytest端到端测试污染真实会话目录](2026-08-12-pytest端到端测试污染真实会话目录.md) | 会话列表大量空会话（仅 meta 行无消息） | TestClient 测试未隔离 `SESSIONS_ROOT`/`DB_PATH`（测试基建） | fixture 补 monkeypatch 隔离 + 清理 374 个空会话；test_purpose/test_multiuser 65 绿、跑测后文件数零变化 | TestClient 测试三隔离标配；新增端到端测试前检查 fixture；跑完查会话目录文件数 |
| 2026-08-12 | [工作区被误注册为local型无法git更新](2026-08-12-8aca780f-工作区被误注册为local型无法git更新.md) | sync_workspace 报「不是 git 型，不支持拉取」 | 8-11 register-local 覆盖了 7-27 的 git 注册（配置层） | 修正 registry.yaml（type 改回 git + active=tdm + local_path 完整相对路径），pull 成功 6aa29e6→84f011c3 | 重注册前查 audit_log 确认类型；注册本地工作区禁止选 _clones/ 目录；修复时 local_path 用完整相对路径 |
| 2026-08-12 | [测试污染真实工作区注册表](2026-08-12-测试污染真实工作区注册表-register_local未隔离.md) | 会话工作区突然消失，registry.yaml 被清空（active/workspaces 均空） | register_local 测试未隔离 REGISTRY_PATH，fixture 依赖顺序错误致 monkeypatch 未生效，同名 tdm 覆盖真实条目后 teardown 删除（测试基建） | 无损重建 registry.yaml（复用 _clones/tdm 不重 clone）；repo/git_repo fixture 改依赖 db；验证 read_spec 恢复 | 注册类测试先隔离 REGISTRY_PATH 且 fixture 依赖顺序正确；测试工作区名禁用真实名；跑完查 registry.yaml |
| 2026-08-14 | [APScheduler闭包job不可序列化](2026-08-14-APScheduler闭包job不可序列化-startup炸94errors.md) | TestClient 全量 94 errors | add_job 传方法内闭包，APScheduler 无法序列化 callable（实现层） | chat_proofread_job 提升模块级函数（683e559） | add_job callable 必须模块级可导入；startup 挂载后必跑全量回归 |
| 2026-08-19 | [T-948群聊快照全量0字节](2026-08-19-T-948-群聊快照全量0字节-CLI契约漂移.md) | 人工介入区「原文加载中…」永续；8 个快照全 0 字节但同步报成功 | sync_chat 读 data.items 而实为 data.messages 等四处字段漂移 + 0 条仍写空文件计成功（实现+测试双缺口） | T-948 chat_store 重写（111ef29）：真实契约快照 fixture + 0 条不落盘 + chats_empty 诚实计数 | 跨进程消费方 mock 必须复用实测契约快照（feishu_cli_contract.py）；先实跑 --format json 再对代码；空结果显式呈现 |
| 2026-08-19 | [T-955b AI分类500与图片附件不可用](2026-08-19-T-955b-AI分类500与图片附件不可用-契约错位.md) | 重新AI分类500；图片全部加载失败；附件点击无响应；自动聚类产出恖为 0 | LLMClient.chat 返回 tuple 而聚类层按 dict 消费 + 图片下载臆造 docs --media-key flag（聊天图应走 im 通道）；mock 自证第三案 | _llm_content 适配层接入 cluster/draft/regen + fetch_image_by_key 改 (message_id, media_key) im 通道（真实 M3 验证产出 2 话题段） | LLM 消费统一经适配层不裸消费；CLI 先实测 --help；跨边界 mock 形状禁按消费代码反推 |
