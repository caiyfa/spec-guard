# 2026-08-24 T-1011 specflow_dir("") 空 emp 回退私有区——共享话题库不可达

## 现象

T-1011 飞书话题通用召回主库验收：离线门禁全绿（test_specstd 1775 / engine_modes 39 /
test_engine 230 / release_check PASS），联网实测 FAIL——共享材料区
`{ws}/.specflow/feishu_pool/_topics.yaml` 种子 4 卡（2 应进摘要）在位，agent 却答
「话题库当前是空的（count: 0）」，system prompt 摘要块也是「近期无非闲聊话题」。
**有数据却答没有**，命中验收简报失败判据。

## 证据链

- 验收 WS 脚本（`agent/sessions/_accept_t1011_ws.py`）全事件证据：`topic(action=list)`
  返回 `count=0`；system prompt 摘要块为诚实空态文案
- 钉案对照实验：同一份种子数据复制到 `admin/` 私有区后实测 **B 全通**
  （search 命中 → read+messages 并行 → 原文 4 条精确回放、群名解析正常）——
  证明召回逻辑本身正确，仅目录解析错
- 代码钉点：`topic_digest._material_root()` 与 `topic_query._root()` 均调
  `specflow_dir("")`；而 `specflow_dir` 空 emp 参数走 `_resolve_emp("")` 回退
  请求上下文工号（`auth._authenticate` 每个请求 `set_context_emp_no`），
  Web 登录态下恒解析 `{ws}/.specflow/{emp}/` 私有区——共享区永远够不着
- 测试盲区：原 25 个测试全部显式传 `material_root` 或无 emp 上下文，
  恰好绕开生产解析路径

## 根因

工作区目录解析层（配置/基建）：`specflow_dir("")` 的「空 emp = 共享区」契约
被请求上下文 emp 静默击穿——与 T-014 `reports_dir` 404 事故**同一形态**
（specguard_dir 当年同因已加 force_shared），specflow_dir 漏随 specguard_dir
同步该参数，新消费方按直觉调空参即踩雷。

## 修复

- `specstd/ws_dirs.py`：`specflow_dir(emp="", force_shared=False)` 镜像
  `specguard_dir` 既有参数（force_shared 时短路 `_emp_subdir`）
- `topic_digest._material_root()` / `topic_query._root()` 改
  `specflow_dir("", force_shared=True)`（feishu_pool = T-949 定位的工作区公共资产，
  天然共享产物）
- 回归测试 +4（test_topic_digest.py `TestSharedRootUnderEmpContext`）：
  emp 上下文 + 生产解析路径（不显式传 root）下 digest/match/tool-list
  均读共享区；修复前必红已反证（同 fixture 旧路径读 0 卡，修复后命中）
- 修复后用验收留档种子（`_clones/tdm/.specflow/feishu_pool/`）在生产路径
  （激活 tdm 工作区 + emp 上下文）实测 A/B/C 全通
- 提交：本分支修复提交（T-1011 打回复修，随复验合并入库）
- **波及面已随 T-1011 同树修复**（总控人 08-24 指令）：路由 `_material_base()` /
  watcher `resolve_material_base()` 改 force_shared；事件直写 `_trigger_pull` 与
  `user_materials_job` 两个旁路补 material_root；`migrate_legacy_pool` 补
  docs/minutes 迁移缺口（T-949 版只迁 chats——三通道 sidecar 随正文）+
  新增 `migrate_all_private_pools` 全员枚举迁移（幂等，只计实际迁移量），
  接线 sync 端点与 watcher start_all（启动自动归拢存量）

## 预防

- **凡是「天然共享」的工作区产物（reports/info_packs/feishu_pool/话题库），
  目录解析必须 `force_shared=True`**——不许调空参依赖「空 emp = 共享区」契约，
  该契约在 Web 登录态下不成立（每个请求都有上下文工号）
- 新增共享区消费方时评审查一点：root 解析是否 force_shared；测试必须覆盖
  「emp 上下文 + 生产解析路径」用例（只测显式传 root = 没测解析）
- **「落盘根」类参数要随调用链全链路排查旁路**：resolver 修对不代表写路径
  全对——`_trigger_pull`（事件直写）与定时 job 曾直传 emp 私有区绕过
  resolver；写路径审计要搜「直接拼接 .specflow/{emp} 的调用点」不止搜
  resolver 调用
- **迁移函数的覆盖面要跟「写入面」对齐**：T-949 迁移只迁 chats 是因为当时
  只审了 chats 写入面；docs/minutes 同根因落私有区却无迁移路径。改共享/
  私有归属时，迁移清单 = 写入面清单，逐通道核对（含 sidecar 文件）
