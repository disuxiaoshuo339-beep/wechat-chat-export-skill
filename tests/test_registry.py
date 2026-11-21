import pytest

from wechat_export.registry import ensure_outside_skill_root, resolve_account


def _registry(tmp_path):
    return {
        "accounts": {"号1": {"account_id": "wxid_x_1a2b", "output_root": str(tmp_path / "out")}},
    }


def test_resolve_account_by_alias_and_id(tmp_path):
    reg = _registry(tmp_path)
    assert resolve_account("号1", reg)[0] == "wxid_x_1a2b"
    assert resolve_account("wxid_x_1a2b", reg)[1]["alias"] == "号1"
    assert resolve_account("wxid_unknown", reg) == ("wxid_unknown", {})


def test_paths_inside_skill_root_are_rejected(tmp_path):
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    for inside in (skill, skill / "runs", skill / "scripts" / ".." / "out"):
        with pytest.raises(RuntimeError, match="不能放在 skill 目录内"):
            ensure_outside_skill_root(inside, "output_root", skill_root=skill)


def test_paths_outside_skill_root_are_allowed(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    # 名字以 skill 目录名开头的兄弟目录不算在里面（不能按字符串前缀判断）
    sibling = tmp_path / "skill-runs"
    assert ensure_outside_skill_root(sibling, "output_root", skill_root=skill) == sibling.resolve()
    assert ensure_outside_skill_root(tmp_path / "pub", "发布目录", skill_root=skill) == (tmp_path / "pub").resolve()
