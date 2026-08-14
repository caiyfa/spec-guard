"""test_feishu_transcribe.py — 图片视觉转述单测（二期 T-920）。

覆盖：
- 无 vision 模型 → skipped（一期行为不变，不报错不阻塞）
- pending → 下载 → vision LLM → done 回填（caption_by=vision_llm）
- 下载/模型失败 → status=failed 诚实呈现
"""

import json
from unittest.mock import MagicMock, patch

from specflow.feishu_pool import captions, pool_store


def _pool_with_pending(tmp_path):
    emp = tmp_path / ".specflow" / "u1"
    pool_store.save_doc_snapshot(
        emp, "tokA", "如图 [图片#1]\n",
        imgmap={"图片#1": {"media_key": "mk_1", "caption": "",
                           "caption_by": "none", "status": "pending"}})
    return emp


def _imgmap(emp):
    return json.loads((emp / "feishu_pool" / "docs" / "fd-tokA.imgmap.json")
                      .read_text(encoding="utf-8"))


def test_skip_without_vision_llm(tmp_path):
    emp = _pool_with_pending(tmp_path)
    out = captions.transcribe_images(emp, llm_vision=None)
    assert out["status"] == "skipped"


def test_transcribe_pending_to_done(tmp_path):
    emp = _pool_with_pending(tmp_path)
    llm = MagicMock()
    llm.chat.return_value = {"content": "权限矩阵架构图"}
    with patch.object(captions, "_download_image", return_value=b"\x89PNG fake"):
        out = captions.transcribe_images(emp, llm_vision=llm)
    assert out["done"] == 1
    img = _imgmap(emp)["图片#1"]
    assert img["caption"] == "权限矩阵架构图"
    assert img["caption_by"] == "vision_llm"
    assert img["status"] == "done"


def test_download_failure_marks_failed(tmp_path):
    emp = _pool_with_pending(tmp_path)
    llm = MagicMock()
    with patch.object(captions, "_download_image",
                      side_effect=ValueError("403 无权限")):
        out = captions.transcribe_images(emp, llm_vision=llm)
    assert out["failed"] == 1
    img = _imgmap(emp)["图片#1"]
    assert img["status"] == "failed"
    assert "403" in img.get("error", "")
