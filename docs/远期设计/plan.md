# Plan: 设计文档补 Mermaid 图（仅 md，不再产 docx）

- 约定：后续所有交付物 = .md；已有 docx 不再更新
- Stage 1（并行 4 个 coder 子代理）为设计文档插入 mermaid 图：
  - A1: 00-模块地图与统一约定 / M01 / M02 / M03
  - A2: M04 / M05 / M06
  - A3: M07 / M08 / M09
  - A4: M10 / M11 / M12 / M13 + 总控文档（阶段依赖图）
- 统一要求：每文件 1-3 张图，插在相关章节（状态机/流程/依赖/数据关系处）；
  只用 graph/flowchart、sequenceDiagram、stateDiagram-v2、erDiagram；
  中文标签用引号包裹；不改写正文，只插入；完成后自检 mermaid 语法
- Stage 2：抽查渲染 + 汇总交付
