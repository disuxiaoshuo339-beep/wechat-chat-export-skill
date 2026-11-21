from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from .screening import SCREENING_HEADERS, _csv_safe

# 关注名单：本 skill 只导出用户点名的人。
# 点名 → 在会话元数据里匹配（零正文）→ 唯一且精确命中的才进会话清单；
# 模糊命中、重名、找不到的一律退回给用户定，不替用户猜。

WATCHLIST_PATH = Path(__file__).resolve().parents[2] / "watchlist.json"
SOURCE_WATCHLIST = "关注名单"
SELECTION_MODE = "watchlist"

NAME_FIELDS = ("备注名", "昵称", "显示名", "微信号", "微信号别名")
ID_FIELDS = ("微信号", "微信号别名")
# 候选超过这个数就不列名字，只报数量：点名太宽（如只说一个姓）时不把无关联系人摊出来
MAX_CANDIDATES = 8


def _norm(value: object) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def match_people(
    rows: list[dict], names: list[str], wxids: list[str]
) -> list[dict[str, object]]:
    """每个点名返回 {query, kind, match_type, matches}。
    wxid：只做微信号 / 微信号别名的精确匹配。
    name：先全等匹配，全等没有才退到包含匹配（包含匹配永远需要用户确认）。"""
    results: list[dict[str, object]] = []
    for raw in wxids:
        query = _norm(raw)
        if not query:
            raise ValueError("点名的微信号不能为空")
        matches = [
            row for row in rows if any(_norm(row.get(field)) == query for field in ID_FIELDS)
        ]
        results.append(
            {"query": raw.strip(), "kind": "wxid", "match_type": "exact", "matches": matches}
        )
    for raw in names:
        query = _norm(raw)
        if not query:
            raise ValueError("点名的名字不能为空")
        exact = [
            row for row in rows if any(_norm(row.get(field)) == query for field in NAME_FIELDS)
        ]
        if exact:
            matches, match_type = exact, "exact"
        else:
            matches = [
                row for row in rows if any(query in _norm(row.get(field)) for field in NAME_FIELDS)
            ]
            match_type = "contains"
        results.append(
            {"query": raw.strip(), "kind": "name", "match_type": match_type, "matches": matches}
        )
    return results


def _brief(row: dict) -> dict[str, object]:
    return {
        key: row.get(key, "")
        for key in ("显示名", "备注名", "昵称", "微信号", "微信号别名", "消息数", "首条时间", "末条时间")
    }


def resolve(results: list[dict[str, object]]) -> dict[str, object]:
    """把匹配结果分成：selected（可直接导出）/ to_confirm（需用户确认）/ not_found。
    只有「精确命中且唯一」才算 selected。"""
    selected: dict[str, dict] = {}
    selected_report: list[dict[str, object]] = []
    to_confirm: list[dict[str, object]] = []
    not_found: list[str] = []
    for result in results:
        matches: list[dict] = result["matches"]  # type: ignore[assignment]
        query = str(result["query"])
        if not matches:
            not_found.append(query)
        elif len(matches) == 1 and result["match_type"] == "exact":
            row = matches[0]
            wxid = str(row["微信号"])
            if wxid not in selected:
                selected[wxid] = row
                selected_report.append({"query": query, **_brief(row)})
        else:
            entry: dict[str, object] = {
                "query": query,
                "reason": "模糊命中" if result["match_type"] == "contains" else "重名",
                "count": len(matches),
            }
            if len(matches) <= MAX_CANDIDATES:
                entry["candidates"] = [_brief(row) for row in matches]
            else:
                entry["hint"] = "候选太多，不列名字；请给更完整的备注名、昵称或微信号"
            to_confirm.append(entry)
    return {
        "rows": list(selected.values()),
        "selected": selected_report,
        "to_confirm": to_confirm,
        "not_found": not_found,
    }


def write_watchlist_csv(rows: list[dict], path: Path) -> None:
    """会话清单只写点名命中的人，整列 Y。没点名的联系人不落盘。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(SCREENING_HEADERS)
        for sequence, row in enumerate(rows, start=1):
            values = {**row, "序号": sequence, "来源": SOURCE_WATCHLIST, "是否导出": "Y"}
            writer.writerow([_csv_safe(values.get(header, "")) for header in SCREENING_HEADERS])


def load_watchlist(path: Path = WATCHLIST_PATH) -> dict:
    if not path.is_file():
        return {"accounts": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def saved_wxids(account_id: str, path: Path = WATCHLIST_PATH) -> list[str]:
    people = load_watchlist(path).get("accounts", {}).get(account_id, {}).get("people", [])
    return [str(person["wxid"]) for person in people if person.get("wxid")]


def remember(
    account_id: str, selected_report: list[dict[str, object]], path: Path = WATCHLIST_PATH
) -> int:
    """把这次点名并确认的人记进 watchlist.json（按微信号去重），返回名单总人数。"""
    data = load_watchlist(path)
    data.setdefault(
        "_说明",
        "关注名单：用户点过名、要导出聊天记录的人。账号 ID → people。"
        "由 select_people.py 维护；要移除某人就删掉对应条目。本文件不入库（.gitignore）。",
    )
    people = data.setdefault("accounts", {}).setdefault(account_id, {}).setdefault("people", [])
    known = {person.get("wxid") for person in people}
    for item in selected_report:
        if item["微信号"] in known:
            continue
        people.append(
            {
                "wxid": item["微信号"],
                "asked_as": item["query"],
                "added": date.today().isoformat(),
            }
        )
        known.add(item["微信号"])
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(people)
