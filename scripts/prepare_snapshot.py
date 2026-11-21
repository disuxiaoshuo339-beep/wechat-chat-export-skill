from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wechat_export.config_cipher import _zero_secret, extract_database_keys  # noqa: E402
from wechat_export.discovery import (  # noqa: E402
    authorize_account,
    default_search_roots,
    discover_accounts,
    get_file_version,
)
from wechat_export.key_scan import enumerate_authorized_weixin_processes  # noqa: E402
from wechat_export.manifest import copy_with_manifest  # noqa: E402
from wechat_export.registry import (  # noqa: E402
    ensure_outside_skill_root,
    resolve_account,
    search_roots,
)
from wechat_export.sqlcipher import decrypt_database, verify_sqlite  # noqa: E402
from wechat_export.wal import apply_encrypted_wal  # noqa: E402


_NEEDED_DB = re.compile(
    r"^(contact/contact|session/session|message/message_\d+|message/media_\d+)\.db$"
)


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", value).strip("._")
    return cleaned or "wechat-account"


def _default_output_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "WeChatChatExport" / "runs"


def _new_run_root(output_root: Path, account_id: str) -> Path:
    account_root = ensure_outside_skill_root(output_root, "output_root") / _safe_component(account_id)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = account_root / f"{stamp}-run"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = account_root / f"{stamp}-run-{suffix}"
    candidate.mkdir(parents=True)
    return candidate


def _write_manifest(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["relative_path", "size_bytes", "modified_utc", "sha256"])
        for row in rows:
            writer.writerow(
                [row.relative_path, row.size_bytes, row.modified_utc, row.sha256]
            )


def _write_state(run_root: Path, payload: dict[str, object]) -> None:
    (run_root / "run-state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _decrypt_snapshot(
    source_copy: Path, destination: Path, needed: re.Pattern[str] = _NEEDED_DB
) -> dict[str, int]:
    # 只解密导出要用的库：联系人、会话、一对一消息分库、语音库（media_N，export_media.py 用）。
    # 朋友圈、收藏、公众号消息、搜索索引等库不解密，明文不落盘。
    database_paths = sorted(
        path
        for path in source_copy.rglob("*.db")
        if path.is_file() and needed.match(path.relative_to(source_copy).as_posix())
    )
    keys = extract_database_keys(source_copy)
    # 4.1.15 起 migrate/ 库的密钥也能取到，keys 会多于 database_paths；
    # 只要求需要解密的库全部覆盖，多出来的密钥立即清零丢弃
    for path in [path for path in keys if path not in set(database_paths)]:
        _zero_secret(keys.pop(path))
    missing = [path for path in database_paths if path not in keys]
    if missing:
        for secret in keys.values():
            _zero_secret(secret)
        names = ", ".join(path.relative_to(source_copy).as_posix() for path in missing)
        raise RuntimeError(
            f"validated keys do not cover all databases: "
            f"{len(database_paths) - len(missing)}/{len(database_paths)}; missing: {names}"
        )
    verified = 0
    wal_frames = 0
    skipped_fts = 0
    try:
        for source_path in database_paths:
            if source_path.name.endswith("_fts.db"):
                skipped_fts += 1
                continue
            relative = source_path.relative_to(source_copy)
            target_path = destination / relative
            result = decrypt_database(source_path, target_path, keys[source_path])
            wal_path = source_path.with_name(source_path.name + "-wal")
            if wal_path.exists() and wal_path.stat().st_size > 32:
                with source_path.open("rb") as stream:
                    database_salt = stream.read(16)
                merged = apply_encrypted_wal(
                    target_path, wal_path, keys[source_path], database_salt
                )
                wal_frames += merged.applied_frames
            integrity = verify_sqlite(target_path)
            if not integrity.ok:
                raise RuntimeError(
                    f"core SQLite verification failed for {relative.as_posix()}: "
                    f"{integrity.detail}"
                )
            verified += 1
        required = [
            destination / "contact" / "contact.db",
            destination / "session" / "session.db",
            destination / "message" / "message_0.db",
        ]
        if not all(path.is_file() for path in required):
            raise RuntimeError("required contact/session/message databases are missing")
    finally:
        for secret in keys.values():
            _zero_secret(secret)
    return {
        "source_databases": len(database_paths),
        "verified_databases": verified,
        "skipped_fts": skipped_fts,
        "wal_frames_applied": wal_frames,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot and decrypt an explicitly authorized local Windows WeChat 4.x account"
    )
    parser.add_argument("--account-id", required=True, help="账号 ID，或 accounts.json 里登记的别名")
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()

    if os.name != "nt":
        raise OSError("Windows is required")
    processes = enumerate_authorized_weixin_processes()
    if not processes:
        raise RuntimeError("no authorized running Weixin.exe process was found")
    version = get_file_version(processes[0].path)
    if version and not version.startswith("4."):
        raise RuntimeError(f"unsupported Weixin version family: {version}")
    roots = args.root or [*search_roots(), *default_search_roots()]
    account_id, entry = resolve_account(args.account_id)
    account = authorize_account(
        discover_accounts(roots, version, len(processes)), account_id
    )
    if not account.core_files_ok:
        raise RuntimeError("authorized account is missing core databases")

    output_root = args.output_root or (
        Path(entry["output_root"]) if entry.get("output_root") else _default_output_root()
    )
    run_root = _new_run_root(output_root, account.account_id)
    state: dict[str, object] = {
        "status": "running",
        "account_id": account.account_id,
        "weixin_version": version,
        "run_root": str(run_root),
        "phases": [],
    }
    _write_state(run_root, state)
    try:
        source_copy = run_root / "source_copy"
        manifest = copy_with_manifest(account.db_storage, source_copy)
        _write_manifest(run_root / "source-manifest.csv", manifest)
        state["phases"].append(
            {"phase": "snapshot", "status": "ok", "files": len(manifest)}
        )
        _write_state(run_root, state)

        decrypted = run_root / "private" / "decrypted"
        decrypt_counts = _decrypt_snapshot(source_copy, decrypted)
        state["phases"].append(
            {"phase": "decrypt", "status": "ok", **decrypt_counts}
        )
        state.update(
            {
                "status": "snapshot_ready",
                "decrypted": str(decrypted),
                "next_action": "运行 select_people.py --name/--wxid 点名（仅元数据，不含正文）",
            }
        )
        _write_state(run_root, state)
        print(
            json.dumps(
                {
                    "status": state["status"],
                    "run_root": str(run_root),
                    "account_id": account.account_id,
                    "weixin_version": version,
                    "source_databases": decrypt_counts["source_databases"],
                    "verified_databases": decrypt_counts["verified_databases"],
                    "wal_frames_applied": decrypt_counts["wal_frames_applied"],
                    "next_action": state["next_action"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["error_type"] = type(exc).__name__
        state["error"] = str(exc)
        _write_state(run_root, state)
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
