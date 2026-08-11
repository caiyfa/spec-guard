"""specflow.lineage — 血缘链谱系口径（M10 §4）。

断链规则集（T-074）：产物落笔即挂链纪律的确定性校验。
规则表 broken_link_rules.yaml（BL-01~BL-06），全部 WARNING 级不阻断流水线；
结果落 {ws}/.specguard/lineage_check.json（派生物，可删可重建）。
"""
