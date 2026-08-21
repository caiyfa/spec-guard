"""evals — Agent 评测体系（T-980，M-C 智能层可信度域）。

轨迹断言先行：golden case（任务 prompt + 期望工具序列/子集 + 产物断言）
+ ScriptedLLM（可编程脚本 LLM）+ 工具结果 mock + metrics.jsonl 工具维度。

入口：`python evals/run_evals.py`（全量）/ `python -m pytest test_specstd/test_evals.py`。
格式与用法见 evals/README.md。
"""
