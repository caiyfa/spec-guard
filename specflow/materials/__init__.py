"""specflow/materials — S3 材料包与信息包（M03）。

子模块：
  store.py           sf_materials / sf_material_topics 表与 CRUD（T-030/T-031）
  pipeline.py        材料解析管线 sniff/extract/chunk（T-030）
  coverage.py        覆盖率机打依据 coverage_map.yaml（T-034）
  pack_assembler.py  信息包六分区装配（T-032/T-033）
"""

from specflow.materials import store, pipeline, pack_assembler, coverage  # noqa: F401
