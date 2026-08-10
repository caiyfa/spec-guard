# SpecGuard 禅道需求读取背景 · S2 面试材料来源

> 版本：v1.0 · 2026-08-10 ｜ 状态：实测验证完成（真实调用 zentao_cli 验证）
> 定位：S2（F1 面试闭环）的议题来源扩展——禅道是产品给研发提供需求的平台，面试素材应能直接引用禅道需求（只读），完整禅道集成（建故事/提单/回写）保持 S5（M06）。
> 关联：总控文档 §4.2 S2 任务（T-020~T-024）、M02（需求面试引擎）、M03（材料包与信息包）、M06（禅道集成）、devops skill（zentao_cli.py）。

---

## 1. 背景：禅道在需求侧的角色

**业务现实**：禅道是目前产品给研发提供需求的平台——需求的**第一现场**在禅道（需求条目/故事/描述/评论/关联 BUG），不只存在于 PRD 文档。

**现有设计定位（M06，S5 交付出口）**：

```
现有假设：产品 → PRD 文档 → (S2 面试) → 冻结 spec → (S5) → 禅道故事
业务现实：产品 → 禅道提需求 ──┬─→ (S2 面试应引用这里的需求上下文)
                              └─→ 研发排期
```

**问题**：若 S2 面试素材只从 PRD 文档/飞书来，会丢失禅道上的需求原文、描述、历史评论、关联 BUG 等第一手上下文——面试官问出的问题可能偏离产品在禅道上的真实意图。

**结论（2026-08-10 决策）**：S2 需要结合禅道信息，但**只做「禅道需求只读引用」薄通道**（方案 A）：
- S2 增补：zentao-cli 只读二命令 `story get` / `story search` → 议题卡 source 支持 `zentao_story` 类型 → 面试官拉取禅道需求文本入信息包；
- S5 保持原样：完整 zentao-cli（建故事/提单/回写/幂等/回滚，见 M06）；
- 理由：只读命令不依赖冻结产物，不违反 T-053 的依赖设计；与飞书通道共用 M03 `_fetched/` 布局与「人拍板 include」闸门；血缘链更完整（禅道需求 → 面试 → 决策 → 冻结 → 禅道故事）。

---

## 2. 禅道 CLI 现状（2026-08-10 实测）

### 2.1 产品定位

| 项 | 值 |
|---|---|
| CLI | `zentao_cli.py`（devops skill：`~/.qoder/skills/devops/scripts/zentao_cli.py`） |
| 凭据 | 自动取 token（account=caiyunfei），`.env.devops` 管理 |
| 目标产品 | **tdm（id=251）「2026版总部人才发展管理系统」**，负责人：蔡云飞 |

### 2.2 现有子命令（`zentao_cli.py --help` 实测）

```
products / bugs / bug-detail / search / summary / executions / my-bugs
create-bug / update-bug / resolve-bug / stories / create-story / batch-detail / analyze
```

| 与 S2 相关 | 命令 | 实测状态 |
|---|---|---|
| ✅ 需求列表 | `stories --product-id 251 [--page --limit --status]` | 验证通过（见 §2.3） |
| ✅ 产品搜索 | `products --search <关键字>` | 验证通过 |
| ❌ 需求详情 | **无 `story get`**（现有 `bug-detail` 只管 BUG） | **S2 需补** |
| ❌ 需求搜索 | **无 `story search`**（现有 `search` 只搜 BUG） | **S2 需补** |
| ⚠️ 需求创建 | `create-story`（已有，属 S5 写通道） | 保持 S5 |

### 2.3 实测结果：人才发展管理系统最近的禅道故事

```bash
python ".../zentao_cli.py" stories --product-id 251 --format json
# → total=1，共 1 条故事：
```

| 字段 | 值 |
|---|---|
| 故事 ID | **ZT-STORY-56746** |
| 标题 | 人才打标AI构建 |
| 状态 | 激活（active） |
| 优先级 | P3（pri=3） |
| 类型 | feature |
| 故事点估算 | 20 |
| 创建人 | 吴赤锐 |

> 实测确认：`--limit 20` 仍 total=1，无分页遗漏；该产品下当前仅此 1 条故事。

---

## 3. S2 禅道只读通道设计（方案 A 落地）

### 3.1 新增 zentao-cli 只读二命令（S2 交付物）

```bash
# 需求详情（S2 新增）
zentao-cli story get --id ZT-STORY-56746
# 出参：{story_id, title, spec(需求描述), acceptance(验收标准), status, pri,
#        category, estimate, opened_by, opened_at, comments[]}（只读，无副作用）

# 需求搜索（S2 新增）
zentao-cli story search --keyword "人才" --product-id 251 [--status active]
# 出参：story 数组（同 stories 列表结构）
```

设计约束：
- **只读**：story get/search 纯 GET 调用，不触任何禅道写接口（写动作全在 S5）；
- **凭据**：沿用 zentao_cli.py 现有凭据管线（token 自动获取，不落日志）；
- **幂等**：只读命令天然幂等，无需 sf_zentao_jobs 作业表（那是 S5 写通道的）；
- **落点**：命令实现放 `integrations/zentao/`（M06 模块包），S2 只实现 get/search 两函数，S5 补 create/update 等。

### 3.2 议题卡 source 扩展（M02 §4.2）

```yaml
source:
  - { type: prd_section, ref: "PRD v3.2 §2.7", material: prd-v3.2.pdf }
  - { type: spq, ref: SPQ-005 }
  - { type: feishu_doc, ref: <docx_token>, url: "..." }        # 飞书（见飞书背景文档）
  - { type: zentao_story, ref: ZT-STORY-56746, url: "https://zentao.tdm.cn/story-view-56746.html", note: "人才打标AI构建" }  # v1.1 禅道需求
```

### 3.3 材料包拉取（M03 fetcher）

- 新增 `specflow/materials/fetchers/zentao_story.py`：`story get` 产物落 `.specflow/{emp}/interviews/IV-xxx/materials/_fetched/zentao-story-56746.json`；
- `sf_materials.fmt` 增加 `zentao_story` 类型；`source_url` 填禅道 story URL；`fetched_by` 填拉取人；
- 与飞书通道共用 M03 状态机（uploaded→parsed→indexed→packed）与「人拍板 include」闸门；
- REST/MCP 扩展：`POST /materials/fetch {type: zentao_story, ref}` + MCP 工具 `feishu_fetch_material` 同类增加 zentao 分支（或独立 `zentao_fetch_story`）。

### 3.4 血缘挂链（M06 sf_external_refs 复用）

| 场景 | 登记行 |
|---|---|
| 面试引用禅道需求 | `(zt_story, ZT-STORY-56746) → (interview, IV-xxx)` —— linked_type 枚举已含 `interview`（M06 §4.1），**无需改表** |
| 面试决策挂禅道 | `(zt_story, ZT-STORY-56746) → (fr_anchor, FR-xxx)` 或 `(decision, D-xxx)` |
| S5 建故事时 | 面试期登记的 zt_story 引用直接复用，故事正文自动携带「面试↔需求」血缘 |

> 注意：S2 面试**只登记引用**（sf_external_refs），**不创建**禅道故事——创建仍由 S5 冻结后触发（铁律：冻结 spec 是故事创建唯一输入）。

---

## 4. 风险与边界（S2 施工前须知）

1. **依赖顺序**：S2 的 story get/search 是 zentao-cli 的**子集实现**，S5 T-053 完整封装时须复用/扩展 S2 代码，避免两套 CLI（`integrations/zentao/` 单包维护）；
2. **权限边界**：禅道只读命令依赖 token 可见范围；产品角色可见的需求 ≠ 测试角色可见（若需角色隔离，走 RBAC 工具白名单，与飞书同哲学）；
3. **写红线**：S2 任何情况下不得调用禅道写接口（create-story/create-bug/update 等一律 S5）；面试期禅道资产零改动；
4. **数据量**：story 详情含 spec/acceptance/comments 全文，入信息包时按 M03 chunk 规则切分，避免撑爆上下文；
5. **与 M06 的归属**：sf_external_refs 表归 M06 所有（S5），S2 面试只做**登记消费方**（调用其登记接口或预留 MCP 工具），不建第二张外部锚点表。

---

## 5. 关联文档

- 总控文档：docs/远期设计/SpecGuard-总控文档.md（§4.2 S2 任务 T-020~T-024；S5 T-053~T-056）
- M02 需求面试引擎：docs/远期设计/specguard-module-design/M02-需求面试引擎.md（§4.2 议题卡 source）
- M03 材料包与信息包：docs/远期设计/specguard-module-design/M03-材料包与信息包.md（§4.1 _fetched/、§5.1 fetch 接口）
- M06 禅道集成：docs/远期设计/specguard-module-design/M06-禅道集成.md（S5 完整通道；sf_external_refs 表）
- 飞书背景文档：docs/远期设计/SpecGuard-飞书CLI能力背景-S2面试材料获取.md（S2 外部材料双通道之一）
- devops skill：`~/.qoder/skills/devops/`（zentao_cli.py 实测命令；context.md 产品别名 tdm=251）
