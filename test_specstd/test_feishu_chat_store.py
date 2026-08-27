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


# ══════════════════════════════════════════════════════════
# T-1016：merge_forward（合并转发）消息解析与渲染
# ══════════════════════════════════════════════════════════

def test_normalize_merge_forward_extracts_image_keys():
    """merge_forward：内嵌图两种占位（![Image](key) 与 [Image: key]）全部提取到
    image_keys（外层 message_id 配对下载依据）；content 原样保留。"""
    from test_specstd.feishu_cli_contract import (MERGE_FORWARD_IMAGE_KEYS,
                                                  MERGE_FORWARD_MESSAGE)
    row = cs.normalize_pull_message(MERGE_FORWARD_MESSAGE)
    assert row["msg_type"] == "merge_forward"
    assert row["image_keys"] == MERGE_FORWARD_IMAGE_KEYS
    assert row["content"].startswith("<forwarded_messages>")   # 原样保留
    assert row["image_key"] == ""     # 非单图消息，单 key 字段置空


def test_parse_forwarded_messages():
    """内层消息解析：'[ISOts+08:00] 发送人:' 头行 + 缩进内容行 → 结构化列表。"""
    from test_specstd.feishu_cli_contract import MERGE_FORWARD_MESSAGE
    subs = cs.parse_forwarded_messages(MERGE_FORWARD_MESSAGE["content"])
    assert len(subs) == 8
    assert subs[0]["sender"] == "曹怡华"
    assert subs[0]["ts"] == "2026-08-21T15:29:08+08:00"
    assert "蔡老师" in subs[0]["text"]
    # 图片占位保留在 text（渲染层替换为图）
    assert "![Image](img_v3_0214p_a8cd9662" in subs[0]["text"]
    # <p> 段落标签剥离（第 2 条 <p>@曹怡华 文件名的问题</p>）
    assert subs[1]["text"] == "@曹怡华 文件名的问题"
    # 多内容行 join（第 7 条：图行 + " & 去掉试试看" 行）
    assert "去掉试试看" in subs[6]["text"]
    # 非 merge_forward 内容 → 空列表（调用方兜底原文）
    assert cs.parse_forwarded_messages("普通文本") == []


def test_render_md_merge_forward_inline(tmp_path):
    """md 派生：merge_forward 单行内联展开（line_ids 一对一不破）——内层
    「发送人: 内容」拍平串联、图片占位入 imgmap（与 image/post 共享序号池）。"""
    from test_specstd.feishu_cli_contract import (MERGE_FORWARD_IMAGE_KEYS,
                                                  MERGE_FORWARD_MESSAGE)
    f = tmp_path / "20260821.jsonl"
    cs.merge_chat_jsonl(f, [cs.normalize_pull_message(MERGE_FORWARD_MESSAGE)])
    md, imgmap, line_ids = cs.render_md_from_jsonl(f)
    lines = [l for l in md.splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("[15:43] 蔡云飞: [合并转发]")
    assert "曹怡华: @蔡云飞 蔡老师" in lines[0]
    # 4 张内嵌图按出现顺序入 imgmap
    assert imgmap["[图片#1]"]["media_key"] == MERGE_FORWARD_IMAGE_KEYS[0]
    assert imgmap["[图片#4]"]["media_key"] == MERGE_FORWARD_IMAGE_KEYS[3]
    assert line_ids == ["om_x100b67b4563770b4b4aadb072d42884"]


# ══════════════════════════════════════════════════════════
# T-1028：飞书链接确定性提取 + 三处渲染口径收敛（render_row_body）
# ══════════════════════════════════════════════════════════

def test_contract_new_pinned_types_normalize():
    """新钉案类型（system/video_chat，实测 2026-08-27）：content 原样入库。"""
    from test_specstd.feishu_cli_contract import (SYSTEM_MESSAGE,
                                                  VIDEO_CHAT_MESSAGE)
    row = cs.normalize_pull_message(SYSTEM_MESSAGE)
    assert row["msg_type"] == "system"
    assert "Meeting has started" in row["content"]
    row = cs.normalize_pull_message(VIDEO_CHAT_MESSAGE)
    assert row["msg_type"] == "video_chat"


def test_extract_feishu_links_measured_shapes():
    """实测链接形状提取：text 消息里的裸 sheets / docx+query+fragment / docx。

    形状来源 2026-08-27 真实池扫描（fehorizon.feishu.cn）；token 值按契约模块
    同纪律轻度改写（形状=语法保留，值不敏感）。
    """
    from test_specstd.feishu_cli_contract import (TEXT_WITH_DOCX_URL,
                                                  TEXT_WITH_DOCX_URL_QF,
                                                  TEXT_WITH_SHEETS_URL)
    links = cs.extract_feishu_links(TEXT_WITH_DOCX_URL["content"])
    assert links == [{"kind": "docx",
                      "token": "CtM6dlgsroTTcBxB73wc6RSRnhd",
                      "url": "https://fehorizon.feishu.cn/docx/CtM6dlgsroTTcBxB73wc6RSRnhd"}]
    # query+fragment 属于 URL 的一部分（F2 匹配只看 token）
    links = cs.extract_feishu_links(TEXT_WITH_DOCX_URL_QF["content"])
    assert links[0]["kind"] == "docx"
    assert links[0]["token"] == "PBrqdIjOtouAUtxatd1csAUin2A"
    assert "?from=vc_group_doc_link#doxcn1cHWDK4Fp9vkR0XD6kPd3e" in links[0]["url"]
    links = cs.extract_feishu_links(TEXT_WITH_SHEETS_URL["content"])
    assert links == [{"kind": "sheets", "token": "MchesjK2nhtfKsthZyvcHa7Xne1",
                      "url": "https://fehorizon.feishu.cn/sheets/MchesjK2nhtfKsthZyvcHa7Xne1"}]


def test_extract_feishu_links_family_paths_and_dedup():
    """同族产品路径（wiki/minutes/base/file，公开 URL 语法合成样）可提取；
    多链接按出现顺序、同 URL 去重；中文标点跟随不吞入 URL。"""
    content = (
        "先看知识库 https://fehorizon.feishu.cn/wiki/XAbc123XYZdef456Ghi，"
        "纪要在 https://fehorizon.feishu.cn/minutes/obcnxyz987654321abcd。"
        "表格 https://fehorizon.feishu.cn/sheets/MchTOKEN000000000001 "
        "以及重复 https://fehorizon.feishu.cn/sheets/MchTOKEN000000000001")
    links = cs.extract_feishu_links(content)
    kinds = [l["kind"] for l in links]
    assert kinds == ["wiki", "minutes", "sheets"]
    assert links[0]["token"] == "XAbc123XYZdef456Ghi"
    assert links[1]["url"].endswith("minutes/obcnxyz987654321abcd")   # 中文句号不入 URL


def test_extract_feishu_links_ignores_non_product_domains():
    """非飞书产品域一律不收（防误吸外部链接）；无链接返回空表。"""
    content = ("对比 github.com/zai-org 与 https://example.com/docx/xxxxx "
               "还有飞书首页 https://www.feishu.cn/ 都不算")
    assert cs.extract_feishu_links(content) == []
    assert cs.extract_feishu_links("") == []
    assert cs.extract_feishu_links(None) == []


def _mixed_rows():
    """混排行集（已按存储排序键排好）：两钉案类型 + 未知合成类型 + text 链接。"""
    from test_specstd.feishu_cli_contract import (SYSTEM_MESSAGE,
                                                  TEXT_WITH_DOCX_URL,
                                                  VIDEO_CHAT_MESSAGE)
    rows = [
        cs.normalize_pull_message(SYSTEM_MESSAGE),
        cs.normalize_pull_message(VIDEO_CHAT_MESSAGE),
        dict(cs.normalize_pull_message(TEXT_WITH_DOCX_URL),
             msg_type="magic_card",                      # 未来未知类型合成样本
             message_id="om_magic_001"),                 # 独立幂等键防合并吞噬
        cs.normalize_pull_message(TEXT_WITH_DOCX_URL),
    ]
    return sorted(rows, key=cs._sort_key)


def test_render_row_body_shared_by_md_view(tmp_path):
    """三处口径收敛①：日级 md 视图逐行 = [HH:MM] 发送人: render_row_body(row)。"""
    rows = _mixed_rows()
    f = tmp_path / "20260827.jsonl"
    cs.merge_chat_jsonl(f, rows)
    md, imgmap, line_ids = cs.render_md_from_jsonl(f)
    lines = [l for l in md.splitlines() if l.strip()]
    assert len(lines) == len(rows)                  # 一行一消息铁律
    assert line_ids == [r["message_id"] for r in rows]
    for line, row in zip(lines, rows):
        hhmm = str(row.get("ts") or "")[11:16]
        sender = str(row.get("sender_name") or row.get("sender_id") or "?")
        assert line == f"[{hhmm}] {sender}: {cs.render_row_body(row)}"


def test_render_row_body_readable_fallbacks():
    """三处口径收敛②：system/video_chat 可读行；未知类型保真降级
    （类型名前缀 + 空白折叠截断摘要），不再是纯占位。"""
    body = cs.render_row_body({"msg_type": "system",
                               "content": "Meeting has started."})
    assert body == "[系统] Meeting has started."
    assert cs.render_row_body({"msg_type": "video_chat",
                               "content": "[Video call]"}) \
        == "[视频通话] [Video call]"
    unknown = {"msg_type": "share_doc_card",
               "content": "<interact>  盘点方案\n  多行卡片内容……"}
    body = cs.render_row_body(unknown)
    assert body.startswith("[share_doc_card消息] ")
    assert "盘点方案 多行卡片内容" in body           # 折叠后仍含关键信息
    assert "\n" not in body


def test_window_source_uses_shared_renderer(tmp_path):
    """三处口径收敛③：多日窗口拼接同样走 render_row_body——merge_forward/
    system/链接文本在窗口视图与日级视图渲染一致（此前窗口只保纯 text）。"""
    from specflow.feishu_pool import topic_cluster as tc
    sha = "deadbeef"
    day = "20260827"
    chats = tmp_path / "feishu_pool" / "chats" / sha
    chats.mkdir(parents=True)
    rows = _mixed_rows()
    cs.merge_chat_jsonl(chats / f"{day}.jsonl", rows)
    text, line_ids, line_ts, used_days = tc._load_window_source(
        tmp_path, sha, [day])
    assert used_days == [day]
    assert line_ids == [r["message_id"] for r in rows]
    # 窗口行 = 日前缀 + 共享渲染正文（与日级视图同源仅差日期段）
    expected = [
        f"[{str(r.get('ts') or '')[5:10]} {str(r.get('ts') or '')[11:16]}] "
        f"{str(r.get('sender_name') or r.get('sender_id') or '?')}: "
        f"{cs.render_row_body(r)}" for r in rows]
    assert [l for l in text.splitlines() if l.strip()] == expected
