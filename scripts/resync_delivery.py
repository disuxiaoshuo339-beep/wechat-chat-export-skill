from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wechat_export.screening import read_selection  # noqa: E402

# 明文库已 purge 后补排除：按改过的会话清单，把交付目录里不再勾选的会话删掉并重算计数。
# 只能删、不能加（加会话需要明文库，得从 prepare_snapshot 重来）。
# 运行目录的 delivery 还完整时：之后依次跑 build_index.py → finalize_delivery.py → publish.py。
# 运行目录只剩 delivery\索引数据.json（交付副本已清理）时：直接在发布目录（run-state 的 published_to）
# 上删文件、重写导出摘要和索引表，不再打 ZIP。


def _type_counts(csv_path: Path) -> Counter:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        return Counter(row.get("消息类型") or "" for row in csv.DictReader(stream))


def resync(run_root: Path, selection: Path) -> dict[str, object]:
    delivery = run_root / "delivery"
    source_path = delivery / "索引数据.json"
    files_root = delivery
    if not (delivery / "聊天记录_CSV").is_dir():
        state = json.loads((run_root / "run-state.json").read_text(encoding="utf-8"))
        files_root = Path(str(state.get("published_to") or ""))
        if not (files_root / "聊天记录_CSV").is_dir():
            raise RuntimeError("运行目录和发布目录都找不到 聊天记录_CSV，无法补排除")
    summary_path = files_root / "导出摘要.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    selected = read_selection(selection)

    keep, drop = [], []
    for row in source["index_rows"]:
        (keep if row["微信号"] in selected else drop).append(row)
    if not drop:
        return {"status": "unchanged", "dropped_conversations": 0}

    directions = source["direction_totals"]
    types = Counter(source.get("type_totals", {}))
    dropped_messages = 0
    for row in drop:
        csv_path = files_root / row["CSV文件"]
        html_path = files_root / row["HTML文件"]
        types.subtract(_type_counts(csv_path))
        dropped_messages += int(row["消息数"])
        directions["我"] -= int(row["我发送"])
        directions["对方"] -= int(row["对方发送"])
        directions["未知"] -= int(row["未知方向"])
        csv_path.unlink()
        html_path.unlink()

    source["index_rows"] = keep
    source["private_conversations"] = len(keep)
    source["private_messages"] = int(source["private_messages"]) - dropped_messages
    source["direction_totals"] = directions
    source["type_totals"] = {key: value for key, value in types.items() if value > 0}
    source["screened_out_conversations"] = int(source.get("screened_out_conversations", 0)) + len(drop)
    source["screened_out_messages"] = int(source.get("screened_out_messages", 0)) + dropped_messages
    if int(source["private_messages"]) != sum(int(directions[key]) for key in ("我", "对方", "未知")):
        raise RuntimeError("direction totals do not reconcile after resync")

    for key in summary:
        if key in source:
            summary[key] = source[key]
    source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if files_root != delivery:
        from build_index import build_index  # noqa: E402  同目录脚本

        built = Path(str(build_index(run_root)["index_path"]))
        target = files_root / built.name
        target.write_bytes(built.read_bytes())
        built.unlink()
        csv_count = len(list((files_root / "聊天记录_CSV").glob("*.csv")))
        html_count = len(list((files_root / "聊天记录_HTML").glob("*.html")))
        if not (csv_count == html_count == len(keep)):
            raise RuntimeError(f"发布目录文件数与索引不一致：CSV {csv_count} / HTML {html_count} / 索引 {len(keep)}")
        return {
            "status": "resynced_published",
            "published_to": str(files_root),
            "dropped_conversations": len(drop),
            "dropped_messages": dropped_messages,
            "private_conversations": len(keep),
            "private_messages": source["private_messages"],
        }
    return {
        "status": "resynced",
        "dropped_conversations": len(drop),
        "dropped_messages": dropped_messages,
        "private_conversations": len(keep),
        "private_messages": source["private_messages"],
        "next_action": "依次运行 build_index.py、finalize_delivery.py、publish.py",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="按改过的会话清单，从交付目录删掉不再勾选的会话（明文库已清理时用）")
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--selection", type=Path)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    try:
        result = resync(run_root, args.selection or run_root / "会话清单.csv")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
