from __future__ import annotations

import csv
import json

import pytest

import run_export as run_export_module
import select_people as select_people_module
from test_pipeline_synthetic import SENTINEL, _build_decrypted_root
from wechat_export.screening import read_selection
from wechat_export.watchlist import MAX_CANDIDATES, match_people, resolve

# 合成库里的四个私聊：wxid_company(示例公司A/老王)、wxid_phone(13812345678/小李)、
# wxid_family(老公/老公，正文含 SENTINEL)、wxid_undecided(老李/老李)。


def _run_root(tmp_path):
    run_root = tmp_path / "wxid_me_0000" / "20240115-100000-run"
    (run_root / "private").mkdir(parents=True)
    _build_decrypted_root(run_root / "private")
    (run_root / "run-state.json").write_text(
        json.dumps({"account_id": "wxid_me_0000", "phases": []}), encoding="utf-8"
    )
    return run_root


def _select(run_root, tmp_path, names=(), wxids=(), from_watchlist=False):
    return select_people_module.select_people(
        run_root, list(names), list(wxids), from_watchlist, tmp_path / "watchlist.json"
    )


def _rows(*specs):
    return [
        {"显示名": remark or nick, "备注名": remark, "昵称": nick, "微信号": wxid, "微信号别名": alias}
        for wxid, remark, nick, alias in specs
    ]


def test_exact_unique_name_is_selected_and_only_that_person_is_written(tmp_path):
    run_root = _run_root(tmp_path)
    result = _select(run_root, tmp_path, names=["小李"])

    assert result["status"] == "awaiting_export"
    assert [item["微信号"] for item in result["selected"]] == ["wxid_phone"]
    assert result["private_conversations_total"] == 4
    # 清单只落点名的人：没点名的联系人连名字都不写进文件
    text = (run_root / "会话清单.csv").read_text(encoding="utf-8-sig")
    assert "wxid_phone" in text
    for other in ("wxid_family", "wxid_company", "wxid_undecided", "老公", "示例公司"):
        assert other not in text
    assert read_selection(run_root / "会话清单.csv") == {"wxid_phone"}
    state = json.loads((run_root / "run-state.json").read_text(encoding="utf-8"))
    assert state["selection_mode"] == "watchlist"
    assert state["watchlist_wxids"] == ["wxid_phone"]


def test_fuzzy_match_is_never_auto_selected(tmp_path):
    run_root = _run_root(tmp_path)
    result = _select(run_root, tmp_path, names=["示例公司"])

    assert result["status"] == "needs_attention"
    assert result["selected"] == []
    assert result["to_confirm"][0]["reason"] == "模糊命中"
    assert [c["微信号"] for c in result["to_confirm"][0]["candidates"]] == ["wxid_company"]
    assert not (run_root / "会话清单.csv").exists()
    assert not (tmp_path / "watchlist.json").exists()


def test_duplicate_names_go_back_to_the_user(tmp_path):
    results = match_people(
        _rows(("wxid_a", "", "阿明", ""), ("wxid_b", "阿明", "别的昵称", "")), ["阿明"], []
    )
    outcome = resolve(results)
    assert outcome["rows"] == []
    assert outcome["to_confirm"][0]["reason"] == "重名"
    assert outcome["to_confirm"][0]["count"] == 2


def test_too_many_candidates_are_counted_not_listed():
    rows = _rows(*[(f"wxid_{i}", f"李{i}号", "", "") for i in range(MAX_CANDIDATES + 1)])
    entry = resolve(match_people(rows, ["李"], []))["to_confirm"][0]
    assert entry["count"] == MAX_CANDIDATES + 1
    assert "candidates" not in entry


def test_not_found_blocks_the_whole_selection(tmp_path):
    run_root = _run_root(tmp_path)
    result = _select(run_root, tmp_path, names=["小李", "查无此人"])

    assert result["status"] == "needs_attention"
    assert result["not_found"] == ["查无此人"]
    assert not (run_root / "会话清单.csv").exists()


def test_wxid_matches_id_or_alias_exactly():
    rows = _rows(("wxid_a", "甲", "", "ming_2020"), ("wxid_ab", "乙", "", ""))
    assert [r["微信号"] for r in resolve(match_people(rows, [], ["MING_2020"]))["rows"]] == ["wxid_a"]
    assert [r["微信号"] for r in resolve(match_people(rows, [], ["wxid_a"]))["rows"]] == ["wxid_a"]
    assert resolve(match_people(rows, [], ["wxid_"]))["not_found"] == ["wxid_"]


def test_watchlist_is_remembered_and_reused(tmp_path):
    run_root = _run_root(tmp_path)
    _select(run_root, tmp_path, names=["小李"])
    saved = json.loads((tmp_path / "watchlist.json").read_text(encoding="utf-8"))
    people = saved["accounts"]["wxid_me_0000"]["people"]
    assert [(p["wxid"], p["asked_as"]) for p in people] == [("wxid_phone", "小李")]

    result = _select(run_root, tmp_path, wxids=["wxid_undecided"], from_watchlist=True)
    assert {item["微信号"] for item in result["selected"]} == {"wxid_phone", "wxid_undecided"}
    assert result["watchlist_size"] == 2


def test_no_names_is_an_error(tmp_path):
    with pytest.raises(RuntimeError, match="没有点名"):
        _select(_run_root(tmp_path), tmp_path)


def test_run_export_exports_only_named_people(tmp_path):
    run_root = _run_root(tmp_path)
    _select(run_root, tmp_path, names=["小李"])
    result = run_export_module.run_export(run_root, run_root / "会话清单.csv")

    assert result["private_conversations"] == 1
    assert result["screened_out_conversations"] == 3
    exported = "".join(
        path.read_text(encoding="utf-8-sig") for path in (run_root / "delivery").rglob("*.*")
    )
    assert "谢谢" in exported
    assert SENTINEL not in exported


def test_run_export_refuses_without_select_people(tmp_path):
    run_root = _run_root(tmp_path)
    header = "序号,显示名,备注名,昵称,微信号,消息数,首条时间,末条时间,来源,是否导出\n"
    (run_root / "会话清单.csv").write_text(
        header + "1,老公,老公,老公,wxid_family,3,,,,Y\n", encoding="utf-8-sig"
    )
    with pytest.raises(RuntimeError, match="只导出用户点名的人"):
        run_export_module.run_export(run_root, run_root / "会话清单.csv")
    assert not (run_root / "delivery").exists()


def test_run_export_refuses_rows_added_outside_the_named_set(tmp_path):
    run_root = _run_root(tmp_path)
    _select(run_root, tmp_path, names=["小李"])
    with (run_root / "会话清单.csv").open("a", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerow([2, "老公", "老公", "老公", "wxid_family", 3, "", "", "", "Y"])
    with pytest.raises(RuntimeError, match="不在本次点名范围内"):
        run_export_module.run_export(run_root, run_root / "会话清单.csv")
    assert not (run_root / "delivery").exists()
