# AgentChat UI 重构 + Settings 多模型 + 斜杠命令

## Summary

4 项改动：① AgentChat 左侧会话树（工作区>会话三级层级）② Settings 多 Tab 可视化配置（多模型管理）③ 模式/技能选择器移至对话框区域 ④ 输入框支持斜杠命令。核心目标：扩大对话展示面积，提升配置灵活性。

---

## Part 1: AgentChat 布局重构（需求 1 + 3）

### 1.1 新建 `SessionTree.tsx` 组件

位置：`workbench/frontend/src/components/SessionTree.tsx`

三级树结构：
```
📂 会话
├── 🗂 tdm (工作区)
│   ├── 20260727_195657_a1b2c3d4  (会话, 按时间倒序)
│   └── 20260726_120000_e5f6g7h8
├── 🗂 inventory
│   └── 20260725_100000_xxxx
└── (未分配工作区)
    └── ...
```

Props:
- `sessions: any[]` — 会话列表（含 workspace 字段）
- `currentSessionId: string`
- `currentWorkspace: string`
- `onSelectSession: (id, workspace) => void`
- `onNewSession: () => void`

功能：
- 按 workspace 分组（二级），会话按 modified 倒序（三级）
- 点击会话加载历史消息
- 顶部「+ 新会话」按钮
- 树宽度 240px，可折叠

### 1.2 重构 `AgentChat.tsx` 布局

从 `max-w-4xl mx-auto` 竖向布局改为全宽左右分栏：

```
┌─────────────────────────────────────────────────┐
│ ┌─────────┐ ┌─────────────────────────────────┐ │
│ │ 会话树   │ │ 对话区（最大化）                  │ │
│ │ (240px) │ │                                 │ │
│ │         │ │  消息列表 (flex-1)               │ │
│ │ tdm     │ │  ...                            │ │
│ │  ├ sess1│ │                                 │ │
│ │  └ sess2│ │                                 │ │
│ │ inv     │ │  ┌─────────────────────────┐    │ │
│ │  └ sess3│ │  │ 输入框 + 模式选择 + 发送  │    │ │
│ │         │ │  └─────────────────────────┘    │ │
│ └─────────┘ └─────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

移除的内容（移到底部输入区或左侧树）：
- 顶部标题区（缩小为一行）
- 顶部模式切换 Tab → 移到底部输入区
- 顶部技能面板 → 移到底部输入区的斜杠命令
- 会话列表抽屉 → 替换为左侧 SessionTree
- 会话信息栏（WS 状态/tokens）→ 移到底部状态栏

### 1.3 底部输入区重构

```
┌───────────────────────────────────────────────────┐
│ [输入框 textarea]                          [发送 ●] │
│ ┌───────────────────────────────────────────────┐ │
│ │ ✨生成 🐛调试 🔍分析 💬对话 | 📋技能(3) | 1.2K ctx │ │
│ └───────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

- 模式选择器：小型按钮组，放在输入框下方左侧
- 技能按钮：显示技能数量，点击展开列表
- 上下文大小：显示当前会话 token 数（从 stats 获取）
- 工作区指示：显示当前工作区名

### 1.4 斜杠命令支持（需求 4）

在输入框中输入 `/` 时弹出命令菜单：

```
/ generate-scenario  — 使用场景生成技能
/ validate-conformance — 使用合规校验技能
/ debug-failure      — 使用失败分析技能
/ mode:generate      — 切换到生成模式
/ mode:debug         — 切换到调试模式
/ mode:analyze       — 切换到分析模式
/ mode:chat          — 切换到对话模式
/ new                — 开始新会话
/ clear              — 清空当前对话
```

实现：
- 监听输入框 `onChange`，检测 `/` 开头
- 弹出浮动菜单（绝对定位在输入框上方）
- 键盘上下选择 + Enter 确认
- 选中后：技能类 → 在消息前添加技能提示；模式类 → 切换模式；操作类 → 执行操作
- ESC 关闭菜单

---

## Part 2: Settings 页面多 Tab 重构（需求 2）

### 2.1 后端：多模型配置

**新建 `workbench/backend/services/model_config.py`**

SQLite 表 `model_configs`：
- `id` TEXT PRIMARY KEY（如 model-001）
- `name` TEXT（显示名，如 "DeepSeek-V4"）
- `base_url` TEXT
- `api_key` TEXT
- `model` TEXT
- `timeout` TEXT DEFAULT '120'
- `temperature` TEXT DEFAULT '0.7'
- `max_context_tokens` TEXT DEFAULT ''
- `max_output_tokens` TEXT DEFAULT ''
- `thinking_enabled` TEXT DEFAULT 'false'
- `reasoning_effort` TEXT DEFAULT ''
- `is_default` INTEGER DEFAULT 0
- `created_at` TEXT
- `updated_at` TEXT

函数：`list_models()`, `get_model(id)`, `create_model(data)`, `update_model(id, data)`, `delete_model(id)`, `get_default_model()`, `set_default(id)`

**修改 `workbench/backend/routers/settings.py`**

新增端点：
- `GET /api/settings/models` — 列出全部模型配置
- `POST /api/settings/models` — 创建模型配置
- `PUT /api/settings/models/{id}` — 更新模型配置
- `DELETE /api/settings/models/{id}` — 删除模型配置
- `POST /api/settings/models/{id}/default` — 设为默认
- `POST /api/settings/models/{id}/probe` — 探测连通性

保留原有 `/api/settings/llm-config` 端点（向后兼容，返回默认模型配置）。

**修改 `agent/llm_client.py`**

- `_load_db_config()` 改为从 `model_configs` 表读取默认模型
- 支持通过 `model_id` 参数选择特定模型

**修改 `workbench/backend/routers/agent.py`**

- `ChatBody` 新增 `model_id: str = ""` 字段
- WS 消息读取 `model_id`，传给 LLMClient

### 2.2 前端：Settings 页面 Tab 化

**重构 `Settings.tsx` 为 Tab 布局**

```
┌──────────────────────────────────────────┐
│ ⚙️ 环境设置                    [保存配置]  │
├──────────────────────────────────────────┤
│ [🗄 数据库] [🧠 模型配置] [📄 YAML] [🔑 SSO] │
├──────────────────────────────────────────┤
│                                          │
│  (Tab 内容区)                             │
│                                          │
└──────────────────────────────────────────┘
```

**Tab 1: 数据库连接**（从现有代码提取）
- 6 字段表单（host/port/user/password/name/charset）
- 测试连接按钮

**Tab 2: 模型配置**（全新）
- 左侧：模型列表（可增删，标记默认模型）
- 右侧：选中模型的编辑表单（9 字段 + 探测按钮 + 保存按钮）
- 添加模型按钮
- 每个模型卡片显示：名称、model、状态（默认/探测结果）

**Tab 3: YAML 编辑器**（从现有代码提取）
- Monaco YAML 编辑器（全宽）
- 右侧配置说明面板（可折叠）
- 快速插入模板按钮

**Tab 4: SSO/其他**（从现有 YAML 中提取 sso 段）
- SSO 域名、App ID 等字段
- 网关地址（tdm_base / hr_center_base / oss_base）

### 2.3 前端：api.ts 新增接口

```typescript
export interface ModelConfig {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  model: string;
  timeout: string;
  temperature: string;
  max_context_tokens: string;
  max_output_tokens: string;
  thinking_enabled: string;
  reasoning_effort: string;
  is_default: boolean;
}

export const modelApi = {
  list: () => request<{ models: ModelConfig[] }>('/settings/models'),
  create: (data) => request<ModelConfig>('/settings/models', { method: 'POST', body: ... }),
  update: (id, data) => request<ModelConfig>(`/settings/models/${id}`, { method: 'PUT', body: ... }),
  delete: (id) => request(`/settings/models/${id}`, { method: 'DELETE' }),
  setDefault: (id) => request(`/settings/models/${id}/default`, { method: 'POST' }),
  probe: (id) => request(`/settings/models/${id}/probe`, { method: 'POST' }),
};
```

---

## Part 3: AgentChat 底部选择器中模型切换

### 3.1 模型选择器

在底部模式选择器旁新增模型下拉：
```
✨生成 🐛调试 🔍分析 💬对话 | 🤖 DeepSeek-V4 ▼ | 📋技能(3) | 1.2K ctx
```

- 调用 `GET /api/settings/models` 获取模型列表
- 选择模型后 WS 消息携带 `model_id`
- 默认选中有 `is_default` 标记的模型

---

## 实施顺序

1. **Part 2 后端**：多模型配置服务 + API（model_config.py + settings.py）
2. **Part 2 前端**：Settings Tab 化 + 模型管理 UI
3. **Part 1.1**：SessionTree 组件
4. **Part 1.2-1.3**：AgentChat 布局重构 + 底部输入区
5. **Part 1.4**：斜杠命令
6. **Part 3**：模型选择器集成到 AgentChat 底部
7. **验证**：TS 编译 + Python 测试 + 浏览器实测

---

## 涉及文件

| 文件 | 改动 |
|------|------|
| `workbench/backend/services/model_config.py` | **新建**：多模型配置 CRUD |
| `workbench/backend/routers/settings.py` | 修改：新增模型 CRUD 端点 |
| `agent/llm_client.py` | 修改：支持 model_id 选择 |
| `workbench/backend/routers/agent.py` | 修改：ChatBody 增 model_id |
| `workbench/frontend/src/components/SessionTree.tsx` | **新建**：会话树组件 |
| `workbench/frontend/src/pages/AgentChat.tsx` | **重写**：左右分栏 + 底部选择器 + 斜杠命令 |
| `workbench/frontend/src/pages/Settings.tsx` | **重写**：Tab 布局 + 多模型管理 |
| `workbench/frontend/src/api.ts` | 修改：新增 modelApi + ModelConfig 接口 |

---

## Assumptions

- 全局侧边栏（App.tsx 的 w-52 aside）保持不变，AgentChat 内部有自己的左右分栏
- 多模型配置存储在 SQLite（与现有 llm_config 同一 DB），旧的单模型配置自动迁移为默认模型
- 斜杠命令在输入框内检测 `/` 开头触发，不影响正常输入中的 `/` 字符（仅在行首或空格后触发）
- Settings 的 YAML 编辑器 Tab 保留 Monaco 编辑器，与表单 Tab 独立（不双向同步）
- 模型选择器在 AgentChat 底部，切换模型后下一条消息使用新模型
