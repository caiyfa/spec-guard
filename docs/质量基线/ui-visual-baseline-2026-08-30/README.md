# UI 视觉基线 · 2026-08-30（T-1044 U4 存档）

> B「Paper 纸面」定稿后 U0→U3 施工完成的五主题视觉基线。
> 用途：后续 UI 变更的人眼回归对照（方案 §七.1「五主题逐一截图对照」的存档面）。
> 复核方式：`python workbench/frontend/scripts/ui_ratchet_check.py --all`（散点防回潮）+
> 本目录截图对照（视觉语义防漂移）。

## 拍摄口径

- 环境：树内工作台（mock 认证，90024166/admin），dist 构建于 d1d8d1c（U3-6 后）
- 页面：`drafts-*` = 草稿评审页（选中 HI-PERM-001——三闸徽章组+两行操作栏+墨色入库钮+冲突预警，
  是 B 语言签名元素最密集的画板）；`agentchat-*` = AgentChat 会话页（新三段顶栏+Tabs 页签条）
- 主题：sg_theme 五档全量（midnight/dusk/oled/light/frost），AgentChat 取深浅两极

## 文件

| 文件 | 内容 |
|---|---|
| drafts-midnight.png | 草稿评审 · 暗夜蓝（默认） |
| drafts-dusk.png | 草稿评审 · 暮光紫 |
| drafts-oled.png | 草稿评审 · 墨黑 |
| drafts-light.png | 草稿评审 · 明亮白（B 主场：墨色 primary 黑底白字、逃逸色根治实证） |
| drafts-frost.png | 草稿评审 · 磨砂 |
| agentchat-midnight.png | AgentChat · 暗夜蓝（三段顶栏+IconButton+StatusBadge） |
| agentchat-light.png | AgentChat · 明亮白（Tabs 墨色下划线+计数丸） |
