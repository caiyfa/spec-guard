"""test_feishu_chat_store.py — T-948 群聊消息存储层测试（JSONL 事实源 + md 派生）。

契约快照纪律：用例消费 test_specstd/feishu_cli_contract.py 的真实 CLI 输出快照
（2026-08-19 实测固化）。所有 mock 必须复用该形状，禁止凭代码期望造字段。
"""

from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent

from test_specstd.feishu_cli_contract import pull_messages  # noqa: E402

from specflow.feishu_pool import chat_store as cs  # noqa: E402


def _pull_msgs():
    return pull_messages()


# ══════════════════════════════════════════════════════════
# 消息归一化（CLI / 事件 → JSONL 行）
# ══════════════════════════════════════════════════════════

def test_normalize_pull_message_real_cli_shape():
    """真实 CLI 形状 → JSONL 行：嵌套 sender 平铺、字符串时间转 ISO、保 position。"""
    row = cs.normalize_pull_message(_pull_msgs()[0])
    assert row["message_id"] == "om_x100b670b24462ca8b146ee0cad5da05"
    assert row["position"] == "3021"
    assert row["sender_id"] == "ou_62fe8d6439bc89e441af35bcf75ea98b"
    assert row["sender_name"] == "蔡云飞"
    assert row["ts"] == "2026-08-18T14:07:00"      # "YYYY-MM-DD HH:MM" → ISO 补秒
    assert row["msg_type"] == "text"
    assert row["reply_to"] == "om_x100b670b2935f0b8dda2dff0eb731ee"
    assert row["origin"] == "pull"
    assert row["image_key"] == ""


def test_normalize_pull_message_deleted():
    """deleted=True：行保留、content 置「[已撤回]」（诚实呈现，不丢行）。"""
    raw = _pull_msgs()[0]
    raw["deleted"] = True
    row = cs.normalize_pull_message(raw)
    assert row["content"] == "[已撤回]"


def test_normalize_event_message_evt_key():
    """事件通道无 message_id → evt:{event_id} 幂等键；毫秒时间戳 → ISO。"""
    ev = {"event_id": "e-001", "sender_id": "ou_a",
          "create_time": "1787064450000", "message_type": "text",
          "content": "事件消息"}
    row = cs.normalize_event_message(ev)
    assert row["message_id"] == "evt:e-001"
    assert row["origin"] == "event"
    assert row["position"] == ""
    assert row["ts"].endswith(":30")               # 1787064450s → 秒=30，本地时间换算


# ══════════════════════════════════════════════════════════
# image_key 提取（Q5 实测：content 内 "[Image: {key}]"）
# ══════════════════════════════════════════════════════════

def test_extract_image_key():
    assert cs.extract_image_key(_pull_msgs()[1]) == \
        "img_v3_0214l_adb29cca-1b8c-4976-8c9b-bfa23a6bd9cg"
    assert cs.extract_image_key(_pull_msgs()[0]) == ""


def test_normalize_pull_message_image():
    """image 消息归一化后 image_key 已提出、content 保留原始串。"""
    row = cs.normalize_pull_message(_pull_msgs()[1])
    assert row["image_key"] == \
        "img_v3_0214l_adb29cca-1b8c-4976-8c9b-bfa23a6bd9cg"


# ══════════════════════════════════════════════════════════
# JSONL 幂等合并
# ══════════════════════════════════════════════════════════

def test_merge_appends_updates_and_sorts(tmp_path):
    f = tmp_path / "20260818.jsonl"
    rows = [cs.normalize_pull_message(m) for m in _pull_msgs()]
    out = cs.merge_chat_jsonl(f, rows)
    assert out == {"added": 2, "updated": 0}
    saved = cs.load_chat_jsonl(f)
    assert [r["message_id"] for r in saved] == \
        ["om_x100b671244a7b510b2a7b48ebe9666a",   # position 3002 在前
         "om_x100b670b24462ca8b146ee0cad5da05"]   # position 3021 在后

    # 同 id 内容变化（updated）+ 新 id（added）
    changed = dict(rows[1], content="编辑后的消息", origin="pull")
    fresh = dict(rows[0], message_id="om_new", position="3030")
    out = cs.merge_chat_jsonl(f, [changed, fresh])
    assert out == {"added": 1, "updated": 1}
    saved = cs.load_chat_jsonl(f)
    assert len(saved) == 3
    assert next(r for r in saved if r["message_id"] == changed["message_id"]
                )["content"] == "编辑后的消息"


def test_merge_sort_evt_fallback_key(tmp_path):
    """position 为空（事件条目）回退 (ts, sender_id) 排序，不炸。"""
    f = tmp_path / "20260818.jsonl"
    a = cs.normalize_event_message(
        {"event_id": "e-1", "sender_id": "ou_b",
         "create_time": "1787064420000", "message_type": "text", "content": "b"})
    b = cs.normalize_event_message(
        {"event_id": "e-0", "sender_id": "ou_a",
         "create_time": "1787064360000", "message_type": "text", "content": "a"})
    cs.merge_chat_jsonl(f, [a, b])
    saved = cs.load_chat_jsonl(f)
    assert saved[0]["message_id"] == "evt:e-0"      # ts 早的在前


# ══════════════════════════════════════════════════════════
# md 派生 + imgmap
# ══════════════════════════════════════════════════════════

def test_render_md_and_imgmap(tmp_path):
    f = tmp_path / "20260818.jsonl"
    cs.merge_chat_jsonl(
        f, [cs.normalize_pull_message(m) for m in _pull_msgs()])
    md, imgmap, line_ids = cs.render_md_from_jsonl(f)
    lines = [l for l in md.splitlines() if l.strip()]
    assert lines[0] == "[09:15] 蔡云飞: [图片#1]"
    assert lines[1].startswith("[14:07] 蔡云飞: @贺文君")
    assert imgmap["[图片#1]"]["media_key"] == \
        "img_v3_0214l_adb29cca-1b8c-4976-8c9b-bfa23a6bd9cg"
    assert imgmap["[图片#1]"]["status"] == "pending"
    # 行号 → message_id 对齐表（聚类 msg_lines 换算依据）
    assert line_ids == ["om_x100b671244a7b510b2a7b48ebe9666a",
                        "om_x100b670b24462ca8b146ee0cad5da05"]


def test_rebuild_md_writes_views(tmp_path):
    """rebuild_views：JSONL 同目录重建 {day}.md + {day}.imgmap.json。"""
    import json as _json
    f = tmp_path / "20260818.jsonl"
    cs.merge_chat_jsonl(
        f, [cs.normalize_pull_message(m) for m in _pull_msgs()])
    cs.rebuild_views(f)
    md = (tmp_path / "20260818.md").read_text(encoding="utf-8")
    assert "[图片#1]" in md
    im = _json.loads((tmp_path / "20260818.imgmap.json").read_text(encoding="utf-8"))
    assert im["[图片#1]"]["media_key"].startswith("img_v3_")


def test_load_missing_returns_empty(tmp_path):
    assert cs.load_chat_jsonl(tmp_path / "nope.jsonl") == []


# ══════════════════════════════════════════════════════════
# T-952a：post/file 消息真实内容解析（实测契约：content 即真实内容载体）
# ══════════════════════════════════════════════════════════

def test_normalize_post_message():
    """post：content 原样存（markdown 化文本）；内嵌图提取 image_keys（可多张）。"""
    from test_specstd.feishu_cli_contract import POST_MESSAGE
    row = cs.normalize_pull_message(POST_MESSAGE)
    assert row["msg_type"] == "post"
    assert "跨平台工作经历" in row["content"]        # 文本主体保留
    assert row["image_keys"] == [
        "img_v3_0214l_f94ffa17-8f78-4319-a049-c7a5bb5dc7fg",
        "img_v3_0214l_95d7879b-8a6a-4624-807e-ac6cd9ddbc0g"]


def test_normalize_file_message():
    """file：content 自描述标签解析出 file_name/file_key；content 原样保留。"""
    from test_specstd.feishu_cli_contract import FILE_MESSAGE
    row = cs.normalize_pull_message(FILE_MESSAGE)
    assert row["msg_type"] == "file"
    assert row["file_name"] == "report_gap_analysis_v9.xlsx"
    assert row["file_key"] == "file_v3_0014n_7dc8629b-ce65-466f-bb1a-fe0f175de1ag"


def test_render_md_post_and_file(tmp_path):
    """md 派生：post 文本+内嵌图占位（多图逐一编号）；file 渲染文件名卡片行。"""
    from test_specstd.feishu_cli_contract import FILE_MESSAGE, POST_MESSAGE
    f = tmp_path / "20260818.jsonl"
    cs.merge_chat_jsonl(f, [cs.normalize_pull_message(POST_MESSAGE),
                            cs.normalize_pull_message(FILE_MESSAGE)])
    md, imgmap, line_ids = cs.render_md_from_jsonl(f)
    lines = [l for l in md.splitlines() if l.strip()]
    # post：文本 + 两张内嵌图占位（post 自身计数与 image 消息共享序号池）
    assert any("跨平台工作经历" in l for l in lines)
    assert "[图片#1]" in md and "[图片#2]" in md
    # 内嵌图进 imgmap（转述链路覆盖 post 附图）
    assert imgmap["[图片#1]"]["media_key"] == \
        "img_v3_0214l_f94ffa17-8f78-4319-a049-c7a5bb5dc7fg"
    assert imgmap["[图片#2]"]["media_key"] == \
        "img_v3_0214l_95d7879b-8a6a-4624-807e-ac6cd9ddbc0g"
    # file：真实文件名渲染（不再是 [file消息] 占位）
    assert any("report_gap_analysis_v9.xlsx" in l for l in lines)
    assert len(line_ids) == 2
