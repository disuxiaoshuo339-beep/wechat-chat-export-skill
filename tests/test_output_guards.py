from __future__ import annotations

import json
import zipfile

import pytest

import prepare_snapshot
import publish as publish_module
from wechat_export.registry import SKILL_ROOT


def _complete_run(tmp_path):
    run_root = tmp_path / "runs" / "wxid_me_0000" / "20240115-100000-run"
    (run_root / "delivery" / "聊天记录_CSV").mkdir(parents=True)
    (run_root / "delivery" / "索引数据.json").write_text("{}", encoding="utf-8")
    (run_root / "delivery" / "聊天记录_CSV" / "a.csv").write_text("x", encoding="utf-8")
    archive = run_root / "微信聊天记录_导出.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("聊天索引.xlsx", "index")
        zf.writestr("聊天记录_CSV/a.csv", "x")
        zf.writestr("导出摘要.json", "{}")
    (run_root / "run-state.json").write_text(
        json.dumps({"status": "complete", "archive": str(archive), "account_id": "wxid_me_0000"}),
        encoding="utf-8",
    )
    return run_root, archive


def test_publish_extracts_and_archives_previous_export(tmp_path):
    run_root, archive = _complete_run(tmp_path)
    pub = tmp_path / "pub"
    previous = pub / "聊天导出_20240101"
    previous.mkdir(parents=True)
    (previous / "聊天索引.xlsx").write_text("old", encoding="utf-8")
    unrelated = pub / "别的文件夹"
    unrelated.mkdir()

    result = publish_module.publish(run_root, pub)

    target = pub / "聊天导出_20240115"
    assert result["published_to"] == str(target.resolve())
    assert (target / "聊天索引.xlsx").read_text(encoding="utf-8") == "index"
    assert result["files"] == 3
    # 上一版按「聊天导出_」前缀挪进 _archive，无关目录不动
    assert not previous.exists()
    moved = list((pub / "_archive").glob("*-被聊天导出_20240115替代/聊天导出_20240101"))
    assert len(moved) == 1 and (moved[0] / "聊天索引.xlsx").is_file()
    assert unrelated.is_dir()
    # 运行目录只留索引数据，ZIP 删掉
    assert [p.name for p in (run_root / "delivery").iterdir()] == ["索引数据.json"]
    assert not archive.exists()


def test_publish_refuses_target_inside_skill_root(tmp_path):
    run_root, archive = _complete_run(tmp_path)
    inside = SKILL_ROOT / "导出结果_不应创建"

    with pytest.raises(RuntimeError, match="不能放在 skill 目录内"):
        publish_module.publish(run_root, inside)

    assert not inside.exists()
    assert archive.is_file()
    state = json.loads((run_root / "run-state.json").read_text(encoding="utf-8"))
    assert "published_to" not in state


def test_new_run_root_refuses_output_root_inside_skill_root():
    for inside in (SKILL_ROOT, SKILL_ROOT / "runs_不应创建"):
        with pytest.raises(RuntimeError, match="不能放在 skill 目录内"):
            prepare_snapshot._new_run_root(inside, "wxid_me_0000")
    assert not (SKILL_ROOT / "runs_不应创建").exists()
    assert not (SKILL_ROOT / "wxid_me_0000").exists()


def test_new_run_root_creates_run_dir_outside_skill_root(tmp_path):
    run_root = prepare_snapshot._new_run_root(tmp_path / "runs", "wxid_me_0000")
    assert run_root.is_dir()
    assert run_root.parent == (tmp_path / "runs" / "wxid_me_0000").resolve()
    assert run_root.name.endswith("-run")


def test_export_media_rejects_target_inside_skill_root(tmp_path):
    import export_media

    with pytest.raises(RuntimeError, match="skill 目录内"):
        export_media.export_media(tmp_path, SKILL_ROOT / "tests")
