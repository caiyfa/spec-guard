# TDM 系统 — SIT 环境叙事

> **状态**：v1 起草（T-506，Agent 辅助起草，待人工审）
> **职责边界**：本文件管「环境叙事」（是什么/拓扑/账号池/资源码/已知坑），结构化配置在 [env.sit.yaml](env.sit.yaml)，凭据与密钥一律不写在此文件（红线）——凭据走 env yaml 占位符 + devops 凭据回退。
> **数据来源**：env.sit.yaml / emp-pool.yaml / 经验包（EX-8200eada）/ 场景库执行记录。

---

## 一、环境定位

- **SIT（系统集成测试）环境**：TDM 干部盘点系统联调验证的默认环境，场景默认 `--env sit`。
- 测试入口：`SpecGuard` 场景引擎通过本环境配置接入；网关为集团内网 HA 入口 `sit-ha.fehorizon.com`（本机可达）。
- 与 UAT/生产的差异：**SIT 权限注册码、账号授权与 UAT/生产不同**——换环境必须先核对「资源码」一节。

## 二、网关与 DB 拓扑

| 组件 | 入口 | 说明 |
|---|---|---|
| TDM 业务网关 | `sit-ha.fehorizon.com/femsp/hr-tdm` | 本机可达的 HA 入口；另有 `sit-tdm.fehorizon.com` 直连网关（按需切换） |
| hr-center 权限中台 | `sit-ha.fehorizon.com/femsp/hr-center` | 权限预言机数据源（resolve_account/权限校验） |
| OSS 附件服务 | `sit-ha.fehorizon.com/femsp/oss` + `studybridge-sync` | 文件上传/下载 |
| SIT MySQL | `mysql-sit03.fehorizon.com:3306/hr_center` | 只读账号（`mcp_read`），用于 DB 校对断言 |

- **版本头坑**：`X-Api-Version` 响应头仅 `sit-tdm` 直连网关返回，`sit-ha` 代理入口会剥掉——走 sit-ha 时 `check_version_header: false`（版本头校验作为独立场景覆盖，不全局强制）。

## 三、账号池

| 角色 | 工号/账号 | 用途 | 状态 |
|---|---|---|---|
| default（主测试账号） | caiyunfei / 90024166 | 业务单元/职层/纵向三维 ALL（配置注释声称 TDM_ADMIN） | ⚠️ **实际无活动创建权限**（见「已知坑」#1） |
| no_access | caiyunfei / 90024166 | fail-secure 场景专用（配合假资源码模拟无权限） | ✅ |
| internal | internal token 服务凭证 | K-055：参数驱动接口专用 | ✅（非敏感信息在 env yaml） |
| create | caiyunfei / 90024166 | 创建类场景账号 | ⚠️ 同 default |
| restricted | TODO_AD / TODO_EMPNO | 受限账号（单平台权限） | ❌ 待用户补充 |

**工号池角色（emp-pool.yaml，执行前 DB 校验）**：

| 角色 | 条件（SQL 校验） | 代表工号 |
|---|---|---|
| snapshot_rich | 有快照记录（≥1 条 tdm_snap_profile） | 90024713 / 90001063 / 90024365 / 90024006 / 90023915 |
| cross_platform | 快照跨 ≥2 平台（corp_code 去重 ≥2） | 90027339 / 90027333 / 90024713 / 90024006 / 90027234 |
| vertical_manager | use_vertical_manager=Y | 90001063 / 90027329 |
| no_snapshot_tdm | TDM 员工表有记录但无快照 | 50000294 / 50000769 / 50001867 / 90000002 / 90000003 |
| dhr_only | 仅 DHR 存在（TDM 无记录） | 80005963 / 80006032 / 80006033 |
| nonexistent | 不存在的工号（404 场景，免校验） | NOTEXIST999 |

## 四、资源码

| 资源码 | 用途 | SIT 状态 |
|---|---|---|
| **VIEW_TELENT_SEARCH** | SIT 权限中台实际注册的 TDM 权限码（`default_resource_code`） | ✅ 已注册 |
| TDM_INV_ACTIVITY | 盘点活动创建/操作权限 | ❌ **SIT 无绑定账号**（见「已知坑」#1） |
| TDM_SNAPSHOT_ARCHIVE | 快照归档（代码兜底值） | ⚠️ 与 SIT 实际注册码不同 |
| TDM_GRID_RESULT / TDM_INV_OPERATION | 九宫格/盘点操作（写型） | ⚠️ 待 SIT 绑定 |
| SG_NONEXIST_RESOURCE | 假资源码（fail-secure 场景专用） | ✅ 故意不存在 |

> ⚠️ **环境切换提醒**：UAT/生产按实际注册码修改 `default_resource_code`；新资源码上线前必须绑定测试账号（环境交付 checklist）。

## 五、已知坑

1. **TDM_INV_ACTIVITY 未授权（EX-8200eada，2026-08-02）**：SIT 权限体系该资源码无绑定账号，default 账号实际无活动创建权限。HTTP 200 但业务失败（`status: 500000`，`data` 为错误消息字符串）→ 插值 `{{activity.json.data.id}}` 报「变量未定义」。**对策**：写型场景首步必须带 `precheck_permission`（无权限首步诚实 SKIP）；排障先看 case 详情的 `body_excerpt` 而非 HTTP 状态；环境侧需为测试账号绑定写型资源码全集（TDM_INV_ACTIVITY / TDM_SNAPSHOT_ARCHIVE / TDM_GRID_RESULT / TDM_INV_OPERATION）。
2. **版本头剥离**：`X-Api-Version` 仅 sit-tdm 直连网关返回，sit-ha 代理剥掉——走 sit-ha 必须 `check_version_header: false`。
3. **DB 只读纪律**：SIT MySQL 只有只读账号（mcp_read），DB 校对断言仅 SELECT；密码缺省时自动回退读 devops `.env.devops`（`SG_DB_PASSWORD` / `SG_SSO_PASSWORD` 可覆盖）。
4. **账号池缺口**：restricted 受限账号未补充——单平台权限过滤类场景（PP-PERM 系列）依赖该账号，未配置时无法真实模拟「部分可见」。

---

> **维护约定**：环境变化（网关切换/账号授权/资源码变更）优先更新本叙事 + env.sit.yaml 双处；本文件**永不写凭据**；新坑登记走「事件驱动联动」管线（排障闭环后追加）。
