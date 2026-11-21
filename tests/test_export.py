from __future__ import annotations

from wechat_export.export import classify_conversation, display_name, safe_file_stem


def test_conversation_classifier_excludes_only_explicit_non_private_accounts():
    assert classify_conversation("room@chatroom") == "group"
    assert classify_conversation("gh_example") == "public"
    assert classify_conversation("filehelper") == "system"
    assert classify_conversation("friend@openim") == "private"
    assert classify_conversation("wxid_friend") == "private"


def test_display_name_prefers_remark_then_nickname_then_alias():
    assert display_name("wxid_x", "备注名", "昵称", "alias") == "备注名"
    assert display_name("wxid_x", "", "昵称", "alias") == "昵称"
    assert display_name("wxid_x", None, "", "alias") == "alias"


def test_safe_file_stem_removes_windows_reserved_characters_and_is_stable():
    stem = safe_file_stem(12, '张三:示例/公司*?"<>|', "wxid_friend")

    assert stem.startswith("0012_张三_示例_公司_")
    assert not any(character in stem for character in '<>:"/\\|?*')
    assert len(stem) <= 90
