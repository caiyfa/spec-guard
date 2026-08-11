"""integrations/zentao/cli.py — zentao-cli 命令行入口（M06，T-053）。

用法：
    python -m integrations.zentao.cli story get --id ZT-STORY-56746
    python -m integrations.zentao.cli story search --keyword 人才 --product tdm
    python -m integrations.zentao.cli story create --product tdm --title "…" --spec "…"
    python -m integrations.zentao.cli story update --id ZT-STORY-4821 --points 5
    python -m integrations.zentao.cli bug get --id ZT-BUG-9917
    python -m integrations.zentao.cli bug create --product tdm --title "…" --steps "…"

凭据约定（M06 §5.1）：
- 只经环境变量注入：SG_ZENTAO_TOKEN / SG_ZENTAO_BASE_URL，永不进 argv
- stdout 末行固定 JSON 结果（{"ok": bool, ...}），其余行为人类可读进度
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from integrations.zentao.api import (
    ZenTaoClient,
    ZenTaoAPIError,
    DEFAULT_BASE_URL,
)

PRODUCT_ALIASES = {"tdm": 251}


def _build_client() -> ZenTaoClient:
    token = os.environ.get("SG_ZENTAO_TOKEN", "").strip()
    base_url = os.environ.get("SG_ZENTAO_BASE_URL", "").strip() or DEFAULT_BASE_URL
    return ZenTaoClient(base_url=base_url, token=token)


def _resolve_product(val: str) -> int:
    v = (val or "").strip().lower()
    if v in PRODUCT_ALIASES:
        return PRODUCT_ALIASES[v]
    return int(v)


def _emit(result: dict) -> int:
    """末行 JSON 输出。"""
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def _handle_story_get(args) -> int:
    client = _build_client()
    try:
        data = client.story_get(args.id)
        story = data.get("story", data)
        print(f"✓ 需求 {args.id}: {story.get('title')}（{story.get('status')}）")
        return _emit({"ok": True, "story": story})
    except ZenTaoAPIError as e:
        print(f"✗ {e.message}", file=sys.stderr)
        return _emit({"ok": False, "error": e.message})


def _handle_story_search(args) -> int:
    client = _build_client()
    try:
        found = client.story_search(args.keyword, _resolve_product(args.product),
                                    status=args.status or "")
        print(f"✓ 命中 {len(found)} 条需求")
        return _emit({"ok": True, "stories": found})
    except ZenTaoAPIError as e:
        print(f"✗ {e.message}", file=sys.stderr)
        return _emit({"ok": False, "error": e.message})


def _handle_story_create(args) -> int:
    client = _build_client()
    data = {
        "product": _resolve_product(args.product),
        "title": args.title,
        "spec": args.spec or "",
        "pri": args.pri or 3,
        "category": args.category or "feature",
    }
    if args.acceptance:
        data["acceptance"] = args.acceptance
    try:
        resp = client.story_create(data)
        story = resp.get("story", resp)
        story_id = str(story.get("id", ""))
        print(f"✓ 禅道故事创建成功 → ZT-STORY-{story_id}")
        return _emit({"ok": True, "story_id": story_id, "story": story})
    except ZenTaoAPIError as e:
        print(f"✗ {e.message}", file=sys.stderr)
        return _emit({"ok": False, "error": e.message})


def _handle_story_update(args) -> int:
    client = _build_client()
    data = {}
    if args.points is not None:
        data["estimate"] = args.points
    try:
        resp = client.story_update(args.id, data)
        print(f"✓ 故事点 {args.points} 已回写禅道（{args.id}）")
        return _emit({"ok": True, "story_id": args.id, "response": resp})
    except ZenTaoAPIError as e:
        print(f"✗ {e.message}", file=sys.stderr)
        return _emit({"ok": False, "error": e.message})


def _handle_bug_get(args) -> int:
    client = _build_client()
    try:
        data = client.bug_get(args.id)
        bug = data.get("bug", data)
        print(f"✓ BUG {args.id}: {bug.get('title')}（{bug.get('status')}）")
        return _emit({"ok": True, "bug": bug})
    except ZenTaoAPIError as e:
        print(f"✗ {e.message}", file=sys.stderr)
        return _emit({"ok": False, "error": e.message})


def _handle_bug_create(args) -> int:
    client = _build_client()
    data = {
        "product": _resolve_product(args.product),
        "title": args.title,
        "steps": args.steps or "",
        "severity": args.severity or 3,
        "openedBuild": args.opened_build or "",
    }
    if args.story:
        data["story"] = args.story
    if args.assignee:
        data["assignedTo"] = args.assignee
    try:
        resp = client.bug_create(data)
        bug = resp.get("bug", resp)
        bug_id = str(bug.get("id", ""))
        print(f"✓ 禅道 BUG 创建成功 → ZT-BUG-{bug_id}")
        return _emit({"ok": True, "bug_id": bug_id, "bug": bug})
    except ZenTaoAPIError as e:
        print(f"✗ {e.message}", file=sys.stderr)
        return _emit({"ok": False, "error": e.message})


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zentao-cli",
                                     description="禅道 CLI（SpecGuard M06）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_story = sub.add_parser("story", help="需求操作")
    story_sub = p_story.add_subparsers(dest="action", required=True)
    p_get = story_sub.add_parser("get", help="需求详情（只读）")
    p_get.add_argument("--id", required=True)
    p_get.set_defaults(handler=_handle_story_get)
    p_search = story_sub.add_parser("search", help="需求搜索（只读）")
    p_search.add_argument("--keyword", required=True)
    p_search.add_argument("--product", default="tdm")
    p_search.add_argument("--status", default="")
    p_search.set_defaults(handler=_handle_story_search)
    p_create = story_sub.add_parser("create", help="创建需求（写）")
    p_create.add_argument("--product", default="tdm")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--spec", default="")
    p_create.add_argument("--acceptance", default="")
    p_create.add_argument("--pri", type=int, default=3)
    p_create.add_argument("--category", default="feature")
    p_create.set_defaults(handler=_handle_story_create)
    p_update = story_sub.add_parser("update", help="更新需求（故事点回写）")
    p_update.add_argument("--id", required=True)
    p_update.add_argument("--points", type=int, required=True)
    p_update.set_defaults(handler=_handle_story_update)

    p_bug = sub.add_parser("bug", help="BUG 操作")
    bug_sub = p_bug.add_subparsers(dest="action", required=True)
    p_bget = bug_sub.add_parser("get", help="BUG 详情（只读）")
    p_bget.add_argument("--id", required=True)
    p_bget.set_defaults(handler=_handle_bug_get)
    p_bcreate = bug_sub.add_parser("create", help="提 BUG（写）")
    p_bcreate.add_argument("--product", default="tdm")
    p_bcreate.add_argument("--title", required=True)
    p_bcreate.add_argument("--steps", default="")
    p_bcreate.add_argument("--severity", type=int, default=3)
    p_bcreate.add_argument("--story", default="")
    p_bcreate.add_argument("--opened-build", default="")
    p_bcreate.add_argument("--assignee", default="")
    p_bcreate.set_defaults(handler=_handle_bug_create)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
