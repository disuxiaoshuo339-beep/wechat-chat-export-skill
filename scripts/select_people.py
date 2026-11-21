from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wechat_export import watchlist  # noqa: E402
from wechat_export.export import scan_private_conversations  # noqa: E402

# 本 skill 的唯一筛选入口：用户点名 → 只把点到的人写进 会话清单.csv。
# 扫描只做 COUNT/MIN/MAX 聚合，不读任何正文。输出里只出现点名命中的人，其余联系人只报总数。


def _read_state(run_root: Path) -> dict[str, object]:
    state_path = run_root / "run-state.json"
    if state_path.is_file():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def _write_state(run_root: Path, payload: dict[str, object]) -> None:
    (run_root / "run-state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def select_people(
    run_root: Path,
    names: list[str],
    wxids: list[str],
    from_watchlist: bool = False,
    watchlist_path: Path = watchlist.WATCHLIST_PATH,
) -> dict[str, object]:
    decrypted = run_root / "private" / "decrypted"
    if not decrypted.is_dir():
        raise RuntimeError(
            "找不到解密后的数据目录：请先运行 prepare_snapshot.py 完成快照与解密"
        )
    state = _read_state(run_root)
    account_id = str(state.get("account_id") or run_root.parent.name)
    wxids = list(wxids)
    if from_watchlist:
        wxids += [
            wxid for wxid in watchlist.saved_wxids(account_id, watchlist_path) if wxid not in wxids
        ]
    if not names and not wxids:
        raise RuntimeError(
            "没有点名任何人：用 --name / --wxid 指定，或用 --from-watchlist 复用已存的关注名单"
        )

    rows = scan_private_conversations(decrypted)
    outcome = watchlist.resolve(watchlist.match_people(rows, names, wxids))
    report: dict[str, object] = {
        "account_id": account_id,
        "private_conversations_total": len(rows),
        "selected": outcome["selected"],
        "to_confirm": outcome["to_confirm"],
        "not_found": outcome["not_found"],
    }
    if outcome["to_confirm"] or outcome["not_found"] or not outcome["rows"]:
        # 有任何一个点名没落到唯一的人，就什么都不写：不导出半份名单
        report["status"] = "needs_attention"
        report["next_action"] = (
            "把 to_confirm 的候选和 not_found 的名字报给用户定；"
            "定下来后用 --wxid <微信号> 精确点名重跑（不要的人直接去掉）"
        )
        return report

    screening_csv = run_root / "会话清单.csv"
    watchlist.write_watchlist_csv(outcome["rows"], screening_csv)
    state.update(
        {
            "status": "awaiting_export",
            "selection_mode": watchlist.SELECTION_MODE,
            "watchlist_wxids": [str(row["微信号"]) for row in outcome["rows"]],
            "screening_csv": str(screening_csv),
            "next_action": "运行 run_export.py 导出点名的会话",
        }
    )
    phases = list(state.get("phases", []))
    phases.append(
        {
            "phase": "select_people",
            "status": "ok",
            "selected": len(outcome["rows"]),
            "private_conversations_total": len(rows),
        }
    )
    state["phases"] = phases
    _write_state(run_root, state)
    report["watchlist_size"] = watchlist.remember(account_id, outcome["selected"], watchlist_path)
    report["status"] = "awaiting_export"
    report["screening_csv"] = str(screening_csv)
    report["next_action"] = state["next_action"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="只选用户点名的人：按备注名/昵称/微信号匹配会话元数据（零正文），"
        "唯一且精确命中的写入会话清单，其余退回用户确认"
    )
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--name", action="append", default=[], help="备注名 / 昵称 / 微信号，可多次")
    parser.add_argument("--wxid", action="append", default=[], help="微信号或微信号别名（精确），可多次")
    parser.add_argument(
        "--from-watchlist", action="store_true", help="把 watchlist.json 里该账号已存的人一并选上"
    )
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    try:
        result = select_people(run_root, args.name, args.wxid, args.from_watchlist)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "awaiting_export" else 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "run_root": str(run_root),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
