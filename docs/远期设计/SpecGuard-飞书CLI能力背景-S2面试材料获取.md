# SpecGuard 飞书 CLI 能力背景 · S2 面试材料获取

> 版本：v1.0 · 2026-08-10 ｜ 状态：实测验证完成（真实调用 lark-cli 验证）
> 定位：S2（F1 面试闭环）开发所需的外部材料获取背景——面试素材（飞书文档/多维表格/会议纪要/聊天记录）如何经飞书 CLI 直接获取，无需人工导出下载。
> 关联：总控文档 §4.2 S2 任务（T-020~T-024）、M02（需求面试引擎）、M03（材料包与信息包）。

---

## 1. 背景：S2 面试闭环的材料来源问题

S2（F1 面试闭环 ★价值拐点）要求产品在 AgentChat 完成「面试→台账→P0 清零→归档」端到端流程（总控文档 §2.1）。面试官 Agent 提问的素材来源（M02 §5.3 提问管线）包括：

- 议题来源：PRD 章节（`topic.yaml source: prd_section`）+ 未闭环 SPQ 反哺（`spq`）
- 材料包（M03）：会议纪要 / 访谈文字记录 / PRD 等办公文档

**现状假设**：这些材料由用户「上传」进入材料包（M03 §5.1 multipart 上传），文件格式限 .md/.docx/.pdf/.txt。

**实测结论（本背景文档核心）**：用户侧的真实需求材料主要存在于**飞书生态**——飞书文档（PRD/方案）、多维表格（需求池/申请台账）、妙记（会议纪要）、群/私聊记录（需求讨论）。这些材料**全部可以经 lark-cli 直接拉取**（文本类内容无需下载），S2 的材料获取通道应从「人工上传」扩展为「飞书 CLI 拉取 + 人工上传」双通道。

---

## 2. 飞书 CLI 现状（2026-08-10 实测）

### 2.1 认证与身份

| 项 | 值 |
|---|---|
| appId | `cli_a96d90ca7d7adbd9`（应用：蔡云飞的飞书智能助手） |
| bot 身份 | ready（openId: ou_283890916ae7a91420e0974acda692d5） |
| user 身份 | 蔡云飞（openId: ou_62fe8d6439bc89e441af35bcf75ea98b），token 自动刷新 |
| 关键 scope | `search:docs:read`（2026-08-10 补充授权）、`docs:*`、`base:*`、`minutes:*`、`im:*`、`drive:drive.metadata:readonly`、`wiki:*`、`sheets:*`、`vc:*`、`task:*` 等 |

### 2.2 技能矩阵（lark-* skills 与 S2 材料类型的映射）

| 材料类型（S2 面试素材） | 飞书技能 | 发现（找最近的） | 读取（拿内容） | 实测状态 |
|---|---|---|---|---|
| 飞书文档（PRD/方案/纪要） | lark-doc / lark-drive | `drive +search --doc-types docx` | `docs +fetch --doc <token> --doc-format markdown` | ✅ 验证通过 |
| 多维表格（需求池/申请台账） | lark-base / lark-drive | `drive +search --doc-types bitable` | `base +url-resolve` → `+base-block-list` → `+record-list` | ✅ 验证通过 |
| 会议纪要（妙记） | lark-minutes | `minutes +search --owner-ids me` | `minutes +detail --minute-tokens <token> --summary/--transcript` | ✅ 验证通过 |
| 群聊记录 | lark-im | `im +chat-list --sort active_time` | `im +chat-messages-list --chat-id <id>` | ✅ 验证通过 |
| 私聊记录 | lark-im | `im +chat-list --types p2p` | 同上（--user-id 自动解析 p2p chat_id） | ✅ 验证通过 |

### 2.3 已验证的命令链路（含真实参数）

```bash
# ① 文档：最近 30 天编辑的 docx（发现）
lark-cli drive +search --as user --query "" --edited-since 30d --doc-types docx --sort edit_time --page-size 5 --format json
# ② 文档：读正文（内容）
lark-cli docs +fetch --as user --doc "FBxodQkaJoUicrxdk67cUkbhnwc" --doc-format markdown --format json

# ③ 多维表格：最近编辑的 bitable（发现）
lark-cli drive +search --as user --query "" --edited-since 30d --doc-types bitable --sort edit_time --page-size 5 --format json
# ④ 多维表格：wiki 链接解析出 base_token → 表结构 → 记录
lark-cli base +url-resolve --url "https://fehorizon.feishu.cn/wiki/TP9SwQc7YioIF2kL63BcYC0Rn9g" --as user --format json
lark-cli base +base-block-list --base-token "A4jbbpcKoa9IsosH9S7cSe0onNf" --as user --format json
lark-cli base +record-list --base-token "A4jbbpcKoa9IsosH9S7cSe0onNf" --table-id "tblhlPqR4fg4Bl8g" --as user --page-size 2 --format json

# ⑤ 妙记：我拥有的最近妙记（发现）
lark-cli minutes +search --owner-ids me --page-size 5 --format json
# ⑥ 妙记：AI 总结 + 关键词（内容，--transcript 可追加逐字稿）
lark-cli minutes +detail --minute-tokens obcn5poq178t8s54u29562k6 --summary --keyword --format json

# ⑦ 群聊：按活跃度列出（发现）
lark-cli im +chat-list --as user --sort active_time --page-size 10 --format json
# ⑧ 群聊：拉消息（内容；私聊用 --user-id ou_xxx 自动解析）
lark-cli im +chat-messages-list --as user --chat-id oc_26dc885ce8f4b0133ee5fdcc655adda3 --page-size 3 --format json
```

### 2.4 「直接获取 vs 需要下载」边界（实测确认）

| 内容类型 | 获取方式 | 需要下载？ |
|---|---|---|
| 文档正文（markdown/xml 全文）、目录 | `docs +fetch` 直接返回 | ❌ 无需 |
| 妙记 AI 总结/待办/章节/关键词 | `minutes +detail --summary/--todo/--chapter/--keyword` 直接返回 | ❌ 无需 |
| 多维表格记录、字段、表结构 | `base +record-list` / `+base-block-list` 直接返回 | ❌ 无需 |
| 聊天消息文本、发送人、时间 | `im +chat-messages-list` 直接返回 | ❌ 无需 |
| 文档内嵌图片/附件、消息图片/文件/音视频 | `docs +media-download` / `im +messages-resources-download` / `--download-resources` | ✅ 二进制需下载 |
| 妙记逐字稿（原始发言） | `minutes +detail --transcript` 落地本地文件 | ⚠️ 落盘为 transcript.txt |
| 妙记录音/视频源文件 | `minutes +download` | ✅ 需下载 |

### 2.5 权限注意点（2026-08-10 实测踩坑）

1. `drive +search` 需要 `search:docs:read` scope——**初期未授权**，`auth login --scope "search:docs:read"` 补充后可用；
2. `drive files list` 需要 `space:document:retrieve`（与 +search 不同，**未授权**，发现类一律走 +search）；
3. user 身份缺 scope 时按 lark-shared split-flow 授权（先 `--no-wait --json` 拿 verification_url + 二维码，用户完成后再 `--device-code` 续登）；
4. bot 身份看不到用户个人资源（日历/云空间/私聊），材料拉取一律 `--as user`；
5. `im +chat-messages-list` 拉 p2p 私聊需 `--as user`（bot 不支持枚举 p2p）。

---

## 3. 对 S2 开发的启示（接入建议）

### 3.1 材料来源扩展（M03 主改造点）

| 现有（M03 v1） | 建议扩展（S2 施工时） |
|---|---|
| 材料仅人工 multipart 上传 | **双通道**：人工上传 + 飞书 CLI 拉取（`feishu_fetch` 工具） |
| 格式限 .md/.docx/.pdf/.txt | 增加飞书原生类型：`feishu_doc`（docs +fetch 产物）、`feishu_base`（+record-list 产物）、`feishu_minutes`（+detail 产物）、`feishu_im`（+chat-messages-list 产物） |
| 材料包绑定 iv_id 上传 | 拉取通道同样落 `.specflow/{emp}/interviews/IV-xxx/materials/`，原文以 `_fetched/` 与上传 `_parsed/` 分目录 |
| 无来源追溯 | 飞书拉取材料记录 `source_url`（app_link/docx url/wiki url）+ 拉取时间，供议题卡 source 挂链（对应 M02 topic.yaml `source: prd_section` 扩展为 `source: feishu_doc` 等） |

### 3.2 面试官 Agent 工具白名单（M02 联动）

- 新增 `feishu_fetch` 系列 MCP 工具（或封装为 skill 供面试官调用）：`feishu_search_recent`（发现最近材料，对应 2.3 ①③⑤⑦）、`feishu_fetch_doc/base/minutes/im`（内容拉取）；
- 白名单约束（M01 purpose 机制）：需求面试用途才挂飞书拉取工具；写工具只写 `.specflow/`，飞书侧**纯读**（`docs +fetch`/`+record-list`/`minutes +detail`/`im +chat-messages-list` 全部只读，无副作用，符合「校验器/只读工具无副作用」铁律）；
- 拉取内容入信息包后仍走 M03 闸门（人拍板 include 才生效），飞书拉取不绕过「人拍板」铁律。

### 3.3 与 M04 的联动点

- 五维评分「需求覆盖率」的机打依据（coverage_map.yaml）可消费飞书文档章节产物（`docs +fetch --scope section` 按 § 切分）；
- 决策台账 D-xxx 的 `fr_refs`/`spq_ref` 挂链可扩展飞书材料来源（`source: feishu_minutes` 对应妙记 token），血缘链（M10）增加「材料→飞书 URL」边。

### 3.4 验收建议（F3 验收标准增补）

在 M03 §9 F3 验收标准基础上增补：
1. 面试会话内输入飞书文档 URL / 多维表格 URL / 妙记链接 → 材料自动入包（状态机 uploaded→parsed→indexed→packed 走通），内容与 `docs +fetch` / `+record-list` 返回一致；
2. 飞书拉取材料 sha256_12 可复算（内容指纹），`_fetched/` 与 `_parsed/` 分离可重建；
3. 未授权 scope 时工具返回确定性错误 + 授权引导（不静默降级为 bot 或伪数据）。

---

## 4. 风险与边界（S2 施工前须知）

1. **scope 依赖**：飞书拉取依赖 user 已授权 `search:docs:read` + `docs:*` + `base:*` + `minutes:*` + `im:*`；多用户部署（M6-M8）下每个用户需各自授权，授权状态需在信息包/材料状态中可见（对应 M03「新鲜度可见」哲学）；
2. **私聊拉取限制**：p2p 仅 user 身份可枚举/拉取；bot 身份不可见用户私聊——多用户 RBAC 下「产品视角拉自己的讨论记录」可用，「应用统一拉取」不可行；
3. **逐字稿/二进制边界**：妙记逐字稿与音视频、消息附件需下载落盘；S2 若只消费文本（总结/章节/关键词）则全链路零下载；
4. **内容量约束**：`drive +search --query` 上限 30 字符、`im +chat-messages-list` 单页 50 条、`minutes +search` 时间范围上限 1 个月——批量拉取需分页/分窗，工具封装时注意；
5. **飞书侧只读红线**：本通道只做只读拉取，绝不写飞书资源（不加评论/不建文档/不改表格），写操作仍走 SpecGuard 自有产物域。

---

## 5. 关联文档

- 总控文档：docs/远期设计/SpecGuard-总控文档.md（§4.2 S2 任务 T-020~T-024）
- M02 需求面试引擎：docs/远期设计/specguard-module-design/M02-需求面试引擎.md
- M03 材料包与信息包：docs/远期设计/specguard-module-design/M03-材料包与信息包.md
- M04 决策台账与五维评分：docs/远期设计/specguard-module-design/M04-决策台账与五维评分.md
- 飞书技能：.qoder/skills/lark-doc / lark-base / lark-minutes / lark-im / lark-drive / lark-shared
