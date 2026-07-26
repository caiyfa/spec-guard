# ── 工作副本（源文件: changes/post-launch-fixes/modules\system-settings-platform-corp\delta-spec.md）──
# Delta: 平台业务单元查询 — 底表修正

**基线文件**：`specs/system-settings/platform-corp/spec.md`
**Delta 代号**：`post-launch-fixes`
**变更类型**：MODIFIED

---

## MODIFIED Requirements

### FR-001: 数据权限过滤与底表修正  [delta:post-launch-fixes]

- **原**：系统必须根据当前用户的数据权限过滤返回的业务单元数据（通过前端传入的 resourceCode 调用 HR Center 权限 API 获取 corpCodes 列表），数据来源为 `sap_platform_corp` 表
- **新**：系统必须根据当前用户的数据权限过滤返回的业务单元数据（通过前端传入的 resourceCode 调用 HR Center 权限 API 获取 corpCodes 列表），数据来源为 `sap_corp` 表（业务单元主数据表，包含 corpCode + corpName 等字段）
- **原因**：`sap_platform_corp` 为平台-业务单元映射关系表，不含完整的业务单元主数据；`sap_corp` 才是业务单元主数据表，能提供正确的 corpCode/corpName 下拉选项

**代码核实**：当前 `SapPlatformCorpEntity` 注解 `@TableName("sap_platform_corp")`，代码中无 `sap_corp` 相关实体。涉及修改：
- `SapPlatformCorpEntity.java` → 新建 `SapCorpEntity`（或修改 @TableName）
- `SapPlatformCorpRepository.java` → 新建 `SapCorpRepository`（或修改查询逻辑）
- `PlatformCorpService.java` → 切换依赖的 Repository
- `DataPermissionService.java` 中 `findAllCorpCodes()` 也引用了 `SapPlatformCorpRepository`，需同步修改
- `resolveCorpNames()` 方法被快照收集器使用，需确认切换后不影响快照 corpName 解析

→ task: [PLF-01]

---

## MODIFIED Entities

### §5 Key Entities 变更

| 实体 | 对应表 | 说明 |
|------|--------|------|
| ~~平台业务单元映射~~ | ~~`sap_platform_corp`~~ | ~~存储平台编码与业务单元编码的映射关系~~ |
| 业务单元主数据 | `sap_corp` | 业务单元主数据表，提供 corpCode + corpName |

---

## 合并检查清单

☐ MODIFIED FR-001 → 替换基线 §4 FR-001 描述
☐ MODIFIED §5 → 替换基线 §5 实体表
☐ Changelog 追加 ☐ log.md 追加 ☐ 移至 archive/
