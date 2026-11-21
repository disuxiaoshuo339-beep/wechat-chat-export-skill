from __future__ import annotations

import csv
from pathlib import Path


SCREENING_HEADERS = [
    "序号", "显示名", "备注名", "昵称", "微信号", "消息数", "首条时间", "末条时间",
    "来源", "是否导出",
]

_SELECTED_VALUES = {"Y", "YES", "是", "1", "TRUE", "T", "√"}


def _csv_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _read_csv_text(path: Path) -> str:
    # 用 Excel 改过再另存为「CSV（逗号分隔）」时，中文版默认写 GBK 而不是 UTF-8，所以要能读回 GBK。
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gbk", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as error:
            last_error = error
    raise RuntimeError(
        f"会话清单文件编码无法识别（已尝试 UTF-8 与 GBK）：{path}；"
        f"请在 Excel 里另存为「CSV UTF-8（逗号分隔）」后重试（{last_error}）"
    )


def read_selection(path: Path) -> set[str]:
    if not path.is_file():
        raise FileNotFoundError(
            f"找不到会话清单文件：{path}；请先运行 select_people.py 点名生成清单"
        )
    text = _read_csv_text(path)

    selected: set[str] = set()
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        decision = (row.get("是否导出") or "").strip().upper()
        if decision in _SELECTED_VALUES:
            username = (row.get("微信号") or "").strip()
            if username:
                selected.add(username)
    if not selected:
        raise RuntimeError(
            "会话清单里没有任何一行被标记为导出：请在『是否导出』列填 Y 后重跑"
        )
    return selected
