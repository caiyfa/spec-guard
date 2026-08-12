"""delta_doc_writer — MCP 工具：写入/提交 delta 文档（changes/{delta}/ 限定）。

工具：
  write_delta_doc: 写入 changes/{delta}/ 下文件（proposal/delta-spec/manifest/
                   api-delta/delta-specs 等起草区文档），写前 .bak 备份 + 审计 +
                   写后 conformance 校验；不代提交 git。
  commit_delta_changes: 受限提交 changes/{delta}/ 起草区变更（git add + commit，
                   不 push）——前置门禁：conformance 无 ERROR、未冻结；message
                   须 {type}: 前缀。
只读红线：冻结 delta（FREEZE.yaml 凭证）不可写；基线/归档/草稿不可达。
REST（PUT /api/spec/changes/{delta}、POST .../commit）与 MCP 共用服务层。
"""

import json
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TOOLS = [
    Tool(
        name="write_delta_doc",
        description="写入 delta 文档到工作区 changes/{delta_id}/ 目录（delta 起草区："
                    "proposal.md / delta-spec.md / delta.manifest.yaml / api-delta.yaml / "
                    "delta-specs/*.md 等）。写前自动 .bak 备份，写后自动跑 conformance "
                    "校验（verdict 随返回呈现）。冻结 delta（FREEZE.yaml 凭证存在）拒绝写入；"
                    "基线 specs/ 与归档 archive/ 不可达。落盘后不代提交 git——由用户在 spec "
                    "仓库自行 commit。",
        inputSchema={
            "type": "object",
            "properties": {
                "delta_id": {"type": "string", "description": "delta 代号（如 0817）"},
                "filename": {"type": "string",
                             "description": "delta 目录内相对路径（如 delta-spec.md 或 "
                                            "delta-specs/exp-tag.md），禁止绝对路径/.. 越界"},
                "content": {"type": "string", "description": "文件全文（UTF-8 文本）"},
                "workspace": {"type": "string",
                              "description": "工作区名（可选，默认当前激活工作区）"},
            },
            "required": ["delta_id", "filename", "content"],
        },
    ),
    Tool(
        name="commit_delta_changes",
        description="受限提交 changes/{delta_id}/ 起草区变更（git add + commit，不 push）。"
                    "前置门禁：该 delta conformance 校验无 ERROR、未冻结才允许提交；"
                    "提交范围仅限 changes/{delta_id}/（排除 .bak 与 FREEZE.yaml），基线/归档不可达；"
                    "message 为空自动生成 'feat: delta {代号} 文档更新'，自定义须以 {type}: 前缀开头"
                    "（feat/fix/docs/refactor/test/chore）。提交停留在本地仓库，远端推送由人在 spec "
                    "仓库侧手动完成。仅在用户明确确认提交后调用。",
        inputSchema={
            "type": "object",
            "properties": {
                "delta_id": {"type": "string", "description": "delta 代号（如 0817）"},
                "message": {"type": "string",
                             "description": "commit message（可选；空 = 自动生成）"},
                "workspace": {"type": "string",
                              "description": "工作区名（可选，默认当前激活工作区）"},
            },
            "required": ["delta_id"],
        },
    ),
]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    if name == "write_delta_doc":
        return _handle_write_delta_doc(arguments)
    elif name == "commit_delta_changes":
        return _handle_commit_delta_changes(arguments)
    return []


def _handle_write_delta_doc(arguments: dict) -> list[TextContent]:
    try:
        from services.specflow.delta_doc_writer import write_delta_doc
        result = write_delta_doc(
            workspace=str(arguments.get("workspace", "") or ""),
            delta_id=str(arguments.get("delta_id", "") or ""),
            filename=str(arguments.get("filename", "") or ""),
            content=str(arguments.get("content", "") or ""),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "ok": False, "error": f"写入异常: {e}",
        }, ensure_ascii=False, indent=2))]


def _handle_commit_delta_changes(arguments: dict) -> list[TextContent]:
    try:
        from services.specflow.delta_committer import commit_delta_changes
        result = commit_delta_changes(
            workspace=str(arguments.get("workspace", "") or ""),
            delta_id=str(arguments.get("delta_id", "") or ""),
            message=str(arguments.get("message", "") or ""),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "ok": False, "error": f"提交异常: {e}",
        }, ensure_ascii=False, indent=2))]
