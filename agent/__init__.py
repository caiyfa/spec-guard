"""agent — 薄 harness（~300 行）。

核心循环 LLM⇄tools⇄stop + JSONL 会话持久化 + 企业大模型网关客户端。

启动方式：
    python -m agent.cli "生成 PP-RC-008 场景"    # CLI 端到端
"""
