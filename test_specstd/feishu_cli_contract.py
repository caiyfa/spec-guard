"""feishu_cli_contract.py — lark-cli 真实输出契约快照（T-948 契约纪律）。

来源：2026-08-19 对 lark-cli 1.0.85 实测（USERPROFILE=.lark-cli/90024166，
im +chat-messages-list --as user 实跑输出，脱敏裁剪、结构原样保留）。

关键契约点（曾经因字段名臆断导致 4 群 × 2 天全量 0 字节快照——见
docs/经验包 2026-08-19 条目）：
- 消息列表在 data.messages（不是 data.items）
- create_time 是 "YYYY-MM-DD HH:MM" 字符串（不是毫秒时间戳）
- sender 是嵌套对象 {id, name, ...}（不是 sender_name 平铺字符串）
- image 消息的 image_key 藏在 content "[Image: {key}]" 内（无顶层字段）

纪律：所有 mock 必须复用本快照形状，禁止按代码期望造字段。
"""

import copy

_CLI_SNAPSHOT = {
    "ok": True,
    "identity": "user",
    "data": {
        "has_more": True,
        "messages": [
            {
                "chat_id": "oc_8786450d43fc1c453beb1c147d947c03",
                "content": "@贺文君 正好目前数据权限很散乱 这一波升级一下",
                "create_time": "2026-08-18 14:07",
                "deleted": False,
                "message_id": "om_x100b670b24462ca8b146ee0cad5da05",
                "message_position": "3021",
                "msg_type": "text",
                "reply_to": "om_x100b670b2935f0b8dda2dff0eb731ee",
                "sender": {"id": "ou_62fe8d6439bc89e441af35bcf75ea98b",
                           "id_type": "open_id", "name": "蔡云飞",
                           "sender_type": "user"},
                "mentions": [{"id": "ou_5655f02ef27f9520ea95a810e57be430",
                              "key": "@_user_1", "name": "贺文君"}],
                "updated": True,
            },
            {
                "chat_id": "oc_8786450d43fc1c453beb1c147d947c03",
                "content": "[Image: img_v3_0214l_adb29cca-1b8c-4976-8c9b-bfa23a6bd9cg]",
                "create_time": "2026-08-17 09:15",
                "deleted": False,
                "message_id": "om_x100b671244a7b510b2a7b48ebe9666a",
                "message_position": "3002",
                "msg_type": "image",
                "sender": {"id": "ou_62fe8d6439bc89e441af35bcf75ea98b",
                           "id_type": "open_id", "name": "蔡云飞",
                           "sender_type": "user"},
                "updated": False,
            },
        ],
    },
}


def pull_messages() -> list[dict]:
    """快照的深拷贝（测试内修改不污染契约）。"""
    return copy.deepcopy(_CLI_SNAPSHOT["data"]["messages"])


# T-949 实测（2026-08-19）：drive +member-list / +permission-get-setting
# 需要额外 scope，未授权时返回形状如下（ok:false + missing_scopes 清单）。
# 补齐方式：auth login --domain all 重新授权（lark_auth._REQUIRED_SCOPES 已收录）。
_MEMBER_LIST_MISSING_SCOPE = {
    "ok": False,
    "identity": "user",
    "error": {
        "type": "authorization",
        "subtype": "missing_scope",
        "message": "missing required scope(s): docs:permission.member:retrieve",
        "missing_scopes": ["docs:permission.member:retrieve"],
    },
}

_SETTING_MISSING_SCOPE = {
    "ok": False,
    "identity": "user",
    "error": {
        "type": "authorization",
        "subtype": "missing_scope",
        "message": "missing required scope(s): docs:permission.setting:read",
        "missing_scopes": ["docs:permission.setting:read"],
    },
}


def perm_missing_payloads() -> tuple[dict, dict]:
    """权限接口未授权时的真实返回形状（深拷贝）。"""
    return (copy.deepcopy(_MEMBER_LIST_MISSING_SCOPE),
            copy.deepcopy(_SETTING_MISSING_SCOPE))


# 权限接口成功返回的宽容解析输入（成功形状未实测——解析器兼容多键名，
# 待真实 token 补授权后校准固化）。
MEMBER_LIST_OK = {
    "ok": True,
    "data": {"members": [
        {"member_id": "ou_owner", "member_type": "user", "perm": "full_access"},
        {"member_id": "oc_group", "member_type": "chat", "perm": "view"},
    ]},
}

SETTING_OK = {
    "ok": True,
    "data": {"link_share_entity": "tenant_readable",
             "external_access": False},
}


# T-952 实测（2026-08-19）：post/file 消息的 content 形状——
# post：CLI 已把富文本转 markdown 化文本，内嵌图片引用为 ![Image](key)（可多张）；
# file：自描述标签 <file key="..." name="文件名"/>。
POST_MESSAGE = {
    "chat_id": "oc_8786450d43fc1c453beb1c147d947c03",
    "content": "@蔡云飞 跨平台工作经历的逻辑\n"
               "![Image](img_v3_0214l_f94ffa17-8f78-4319-a049-c7a5bb5dc7fg)\n"
               "2、担任本岗位时间\n"
               "![Image](img_v3_0214l_95d7879b-8a6a-4624-807e-ac6cd9ddbc0g)",
    "create_time": "2026-08-18 14:06",
    "deleted": False,
    "message_id": "om_post_001",
    "message_position": "3020",
    "msg_type": "post",
    "sender": {"id": "ou_62fe8d6439bc89e441af35bcf75ea98b",
               "id_type": "open_id", "name": "贺文君",
               "sender_type": "user"},
    "updated": False,
}

FILE_MESSAGE = {
    "chat_id": "oc_8786450d43fc1c453beb1c147d947c03",
    "content": '<file key="file_v3_0014n_7dc8629b-ce65-466f-bb1a-fe0f175de1ag" '
               'name="report_gap_analysis_v9.xlsx"/>',
    "create_time": "2026-08-19 12:12",
    "deleted": False,
    "message_id": "om_file_001",
    "message_position": "3030",
    "msg_type": "file",
    "sender": {"id": "ou_62fe8d6439bc89e441af35bcf75ea98b",
               "id_type": "open_id", "name": "蔡云飞",
               "sender_type": "user"},
    "updated": False,
}

# T-1016 实测（2026-08-26）：merge_forward（合并转发）消息 content 形状——
# <forwarded_messages> 包裹，内层每条消息为 "[ISO时间戳+08:00] 发送人:" 头行
# + 4 空格缩进内容行（可多行）；内嵌图片两种占位混排：![Image](key)（post 风
# 格）与 [Image: key]（image 消息风格）。来源：群 4d7f814d 落盘 JSONL 行
# om_x100b67b4563770b4b4aadb072d42884（pull 通道原样 content，结构原样保留）。
MERGE_FORWARD_MESSAGE = {
    "chat_id": "oc_8786450d43fc1c453beb1c147d947c03",
    "content": (
        "<forwarded_messages>\n"
        "[2026-08-21T15:29:08+08:00] 曹怡华:\n"
        "    @蔡云飞 蔡老师，这个应该怎么处理呀\n"
        "    ![Image](img_v3_0214p_a8cd9662-24ff-4113-a552-61e3fed37b1g)\n"
        "[2026-08-21T15:30:48+08:00] 蔡云飞:\n"
        "    <p>@曹怡华 文件名的问题</p>\n"
        "[2026-08-21T15:31:26+08:00] 蔡云飞:\n"
        "    把空格去掉\n"
        "[2026-08-21T15:31:40+08:00] 蔡云飞:\n"
        "    [Image: img_v3_0214p_b5659d96-eb78-4eb9-b7c6-e6c035afa3ag]\n"
        "[2026-08-21T15:31:47+08:00] 蔡云飞:\n"
        "    这中间有个空格\n"
        "[2026-08-21T15:35:05+08:00] 曹怡华:\n"
        "    还是不行@蔡云飞 \n"
        "    ![Image](img_v3_0214p_f4761b1b-0dd5-4f05-a18d-ed5407786b6g)\n"
        "[2026-08-21T15:35:30+08:00] 蔡云飞:\n"
        "    ![Image](img_v3_0214p_a1b047a5-177b-4de4-ad8f-8c98febddcbg)\n"
        "     & 去掉试试看\n"
        "[2026-08-21T15:35:48+08:00] 蔡云飞:\n"
        "    这个算是特殊字符\n"
        "</forwarded_messages>"
    ),
    "create_time": "2026-08-21 15:43",
    "deleted": False,
    "message_id": "om_x100b67b4563770b4b4aadb072d42884",
    "message_position": "3030",
    "msg_type": "merge_forward",
    "sender": {"id": "ou_62fe8d6439bc89e441af35bcf75ea98b",
               "id_type": "open_id", "name": "蔡云飞",
               "sender_type": "user"},
    "updated": False,
}

# merge_forward 内嵌图 key（按 content 出现顺序，两种占位混合）
MERGE_FORWARD_IMAGE_KEYS = [
    "img_v3_0214p_a8cd9662-24ff-4113-a552-61e3fed37b1g",
    "img_v3_0214p_b5659d96-eb78-4eb9-b7c6-e6c035afa3ag",
    "img_v3_0214p_f4761b1b-0dd5-4f05-a18d-ed5407786b6g",
    "img_v3_0214p_a1b047a5-177b-4de4-ad8f-8c98febddcbg",
]
