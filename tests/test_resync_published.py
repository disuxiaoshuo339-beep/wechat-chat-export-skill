import json

from resync_delivery import resync

HEADER = "序号,显示名,备注名,昵称,微信号,消息数,首条时间,末条时间,来源,是否导出\n"


def _row(n, wx, me, peer):
    return {
        "序号": n, "显示名": wx, "备注名": wx, "昵称": wx, "微信号": wx, "微信号别名": "",
        "消息数": me + peer, "我发送": me, "对方发送": peer, "未知方向": 0,
        "首条时间": "2024-01-01 00:00:00", "末条时间": "2024-02-01 00:00:00",
        "HTML文件": f"聊天记录_HTML/{n:04d}_{wx}.html", "CSV文件": f"聊天记录_CSV/{n:04d}_{wx}.csv",
    }


def test_resync_drops_from_published_dir_when_run_copy_cleaned(tmp_path):
    run_root = tmp_path / "run"
    published = tmp_path / "pub" / "聊天导出_20240115"
    (run_root / "delivery").mkdir(parents=True)
    (published / "聊天记录_CSV").mkdir(parents=True)
    (published / "聊天记录_HTML").mkdir(parents=True)
    rows = [_row(1, "wxid_keep", 1, 1), _row(2, "wxid_drop", 2, 1)]
    for row in rows:
        lines = ["时间,方向,发送者,消息类型,内容,本地消息ID,服务器消息ID"]
        lines += [f"t,我,我,文本,x,{i},{i}" for i in range(row["我发送"])]
        lines += [f"t,对方,c,图片,x,{i},{i}" for i in range(row["对方发送"])]
        (published / row["CSV文件"]).write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        (published / row["HTML文件"]).write_text("<html></html>", encoding="utf-8")
    source = {
        "private_conversations": 2, "private_messages": 5,
        "direction_totals": {"我": 3, "对方": 2, "未知": 0},
        "type_totals": {"文本": 3, "图片": 2},
        "screened_out_conversations": 0, "screened_out_messages": 0, "index_rows": rows,
    }
    (run_root / "delivery" / "索引数据.json").write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    summary = {k: v for k, v in source.items() if k != "index_rows"}
    (published / "导出摘要.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    (run_root / "run-state.json").write_text(json.dumps({"published_to": str(published)}), encoding="utf-8")
    selection = run_root / "会话清单.csv"
    selection.write_text(HEADER + "1,k,,,wxid_keep,2,,,,Y\n2,d,,,wxid_drop,3,,,,\n", encoding="utf-8-sig")

    result = resync(run_root, selection)

    assert result["status"] == "resynced_published"
    assert result["dropped_conversations"] == 1 and result["dropped_messages"] == 3
    assert not (published / rows[1]["CSV文件"]).exists()
    assert not (published / rows[1]["HTML文件"]).exists()
    new_summary = json.loads((published / "导出摘要.json").read_text(encoding="utf-8"))
    assert new_summary["private_conversations"] == 1
    assert new_summary["private_messages"] == 2
    assert new_summary["direction_totals"] == {"我": 1, "对方": 1, "未知": 0}
    assert new_summary["type_totals"] == {"文本": 1, "图片": 1}
    assert new_summary["screened_out_conversations"] == 1
    assert (published / "聊天索引.xlsx").is_file()
    assert not (run_root / "delivery" / "聊天索引.xlsx").exists()
