from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wechat_export.registry import ensure_outside_skill_root, resolve_account  # noqa: E402


def _new_target(base: Path, stamp: str) -> Path:
    # 只建新目录，永不覆盖历次发布
    candidate = base / f"聊天导出_{stamp}"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = base / f"聊天导出_{stamp}_{suffix}"
    return candidate


def publish(run_root: Path, to: Path | None = None) -> dict[str, object]:
    state = json.loads((run_root / "run-state.json").read_text(encoding="utf-8"))
    if state.get("status") != "complete":
        raise RuntimeError("运行未到 complete 终态，先跑完 finalize_delivery.py")
    archive = Path(str(state["archive"]))
    if to is None:
        _, entry = resolve_account(str(state.get("account_id", "")))
        if not entry.get("publish_dir"):
            raise RuntimeError("accounts.json 里该账号没有 publish_dir，请用 --to 指定发布目录")
        to = Path(entry["publish_dir"])
    to = ensure_outside_skill_root(to, "发布目录")
    stamp = run_root.name.split("-")[0]
    if not (len(stamp) == 8 and stamp.isdigit()):
        stamp = datetime.now().strftime("%Y%m%d")
    target = _new_target(to, stamp)
    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC 校验失败：{bad}")
        members = [info for info in zf.infolist() if not info.is_dir()]
        target.mkdir(parents=True)
        zf.extractall(target)
    extracted = [path for path in target.rglob("*") if path.is_file()]
    if len(extracted) != len(members):
        raise RuntimeError(f"解压文件数不一致：{len(extracted)}/{len(members)}")
    # 同一账号目录下的旧版整体挪进 _archive（先归档不删除），统一目录里只留最新一份
    archived = []
    archive_root = to / "_archive" / f"{datetime.now():%Y-%m-%d}-被{target.name}替代"
    for previous in sorted(to.glob("聊天导出_*")):
        if previous.is_dir() and previous != target:
            archive_root.mkdir(parents=True, exist_ok=True)
            previous.rename(archive_root / previous.name)
            archived.append(str(archive_root / previous.name))
    # 发布后运行目录只留 会话清单 / 状态 / 索引数据.json（补排除要用），交付副本与 ZIP 删掉，避免重复堆积
    delivery = run_root / "delivery"
    for child in list(delivery.iterdir()) if delivery.is_dir() else []:
        if child.name != "索引数据.json":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    archive.unlink(missing_ok=True)
    state["archive"] = None
    state["published_to"] = str(target)
    (run_root / "run-state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"status": "published", "published_to": str(target), "files": len(extracted), "archived_previous": archived}


def main() -> int:
    parser = argparse.ArgumentParser(description="把交付 ZIP 解压到账号的发布目录（新建带日期子目录，不覆盖）")
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--to", type=Path, help="发布根目录；缺省用 accounts.json 的 publish_dir")
    args = parser.parse_args()
    try:
        print(json.dumps(publish(args.run_root.resolve(), args.to), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
