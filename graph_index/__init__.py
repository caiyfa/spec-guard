"""graph_index — 图谱索引（M11 · T-070，P-A 支路咽喉）。

确定性派生服务：把散落的链接关系（anchors/covers/DAG/delta/SPQ/plans/reports）
物化为统一 nodes + 类型化边索引（{workspace}/.specguard/graph_index.db），
指纹失效即重建；派生物非事实源，可删可重建，绝不回写任何源文件。
"""
