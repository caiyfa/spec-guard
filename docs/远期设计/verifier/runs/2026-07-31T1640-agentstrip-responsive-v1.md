# 验证记录 · 2026-07-31T1640 · agent-strip 窄栏响应式修复

## 背景
R6 迭代（各智能体功能在各章节结构化展示）浏览器实测发现 bug：
S4/S5 窄侧栏（.panel ~380px）内 `.agent-strip` 管线被挤压，步骤文字塌缩为竖排单字列。

## 修复
`index.html` CSS 新增 8 条 `.panel` 作用域规则（不改 S7 全宽 strip）：
- `.panel .agent-strip{flex-wrap:wrap}` — ag-id + 闸门第一行，管线换行
- `.panel .ag-pipe{flex:1 1 100%;order:3;flex-direction:column}` — 管线纵向堆叠
- `.panel .ag-arr{transform:rotate(90deg)}` — 箭头转下
- `.panel .ag-step{display:flex;align-items:baseline;text-align:left}` — 标签+值横排
- 同步作用于 S5 提 BUG 双入口的独立 `.ag-pipe`

## 静态校验
- 5 个 `<script>` 块 `node --check` 全部通过 ✓

## 浏览器实测（http://127.0.0.1:8419）
| 检查项 | 结果 |
|---|---|
| S4 材料包 strip（📎 材料包解析 Agent） | ✓ 纵向管线，标签+值横排，闸门徽标右上角 |
| S4 产出交付 strip（📊 故事点评估 skill） | ✓ 同上，zendao-cli 演示按钮在 |
| S5 DAG 批次 strip（🧬 测试数据制造 Agent） | ✓ 纵向管线，batch 0/1/2 卡片完整 |
| S5 报告→SPQ（🔬 失败归因 Agent + 提BUG双入口） | ✓ 归因 strip + 入口①/② 结构块均整洁 |
| S7 图谱索引 strip（全宽 .s7-wrap） | ✓ 保持水平单行管线，未受 panel 规则影响 |
| S8 精简版（s8-mini 三列 + 5 张智能体卡） | ✓ 无文本堆砌，图标短句 |
| S8 卡片点击导航（测试数据制造卡 → S5 DAG 页签） | ✓ go('s5') 生效 |

## 结论
PASS — 可发布 v6。截图：/tmp/v6-s4-materials.png / v6-s4-deliver.png / v6-s5-dag.png / v6-s5-spq.png / v6-s7.png / v6-s8.png
