from __future__ import annotations

import pytest

from wechat_export.screening import read_selection

HEADER = "序号,显示名,备注名,昵称,微信号,消息数,首条时间,末条时间,来源,是否导出\n"


def test_read_selection_returns_only_rows_marked_y(tmp_path):
    csv_path = tmp_path / "会话清单.csv"
    csv_path.write_text(
        HEADER
        + "1,示例公司A,示例公司A,老王,wxid_a,10,2024-01-01,2024-02-01,关注名单,Y\n"
        "2,老公,老公,老公,wxid_b,5,2024-01-01,2024-02-01,关注名单,\n"
        "3,阿强,阿强,阿强,wxid_c,3,2024-01-01,2024-02-01,关注名单,?\n",
        encoding="utf-8-sig",
    )
    assert read_selection(csv_path) == {"wxid_a"}


def test_read_selection_raises_when_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_selection(tmp_path / "不存在.csv")


def test_read_selection_raises_when_nothing_selected(tmp_path):
    csv_path = tmp_path / "会话清单.csv"
    csv_path.write_text(
        HEADER
        + "1,老公,老公,老公,wxid_b,5,2024-01-01,2024-02-01,关注名单,\n"
        "2,阿强,阿强,阿强,wxid_c,3,2024-01-01,2024-02-01,关注名单,?\n",
        encoding="utf-8-sig",
    )
    with pytest.raises(RuntimeError):
        read_selection(csv_path)


def test_read_selection_reads_gbk_saved_csv(tmp_path):
    # 中文版 Excel 的「CSV（逗号分隔）」另存为写的是 GBK，必须能读回
    csv_path = tmp_path / "会话清单.csv"
    csv_path.write_bytes(
        (
            HEADER
            + "1,示例公司A,示例公司A,老王,wxid_a,10,2024-01-01,2024-02-01,关注名单,Y\n"
            "2,老妈,老妈,老妈,wxid_b,5,2024-01-01,2024-02-01,关注名单,\n"
        ).encode("gbk")
    )
    assert read_selection(csv_path) == {"wxid_a"}


def test_read_selection_accepts_chinese_yes_marker(tmp_path):
    csv_path = tmp_path / "会话清单.csv"
    csv_path.write_text(
        HEADER
        + "1,示例公司A,示例公司A,老王,wxid_a,10,2024-01-01,2024-02-01,关注名单,是\n"
        "2,阿强,阿强,阿强,wxid_c,3,2024-01-01,2024-02-01,关注名单,?\n",
        encoding="utf-8-sig",
    )
    assert read_selection(csv_path) == {"wxid_a"}
