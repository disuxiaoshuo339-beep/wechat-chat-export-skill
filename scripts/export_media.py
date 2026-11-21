from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from finalize_delivery import _purge_workspace  # noqa: E402
from wechat_export import image_dat  # noqa: E402
from wechat_export.discovery import (  # noqa: E402
    authorize_account,
    default_search_roots,
    discover_accounts,
)
from wechat_export.export import _contact_map, display_name  # noqa: E402
from wechat_export.messages import (  # noqa: E402
    decode_message_content,
    direction_for_private_chat,
    message_type_parts,
    summarize_content,
)
from wechat_export.registry import ensure_outside_skill_root, load_registry, search_roots  # noqa: E402
from wechat_export.watchlist import SELECTION_MODE  # noqa: E402

# 点名的人的图片、语音、视频：发布之后、清明文之前跑。
#   语音：media_N.db 里的 SILK → mp3（要 accounts.json 的 silk_python 指向装了 pilk 的解释器，和 ffmpeg）
#   图片：msg\attach\<md5(微信号)>\ 下的 .dat 解密，优先原图，其次普通图，最后缩略图
#   视频：msg\video\ 下的 mp4 原样拷贝
# 只处理 run-state 里这一轮点名的微信号。微信数据目录只读。

_TZ = ZoneInfo("Asia/Shanghai")
_MD5 = re.compile(rb"[0-9a-f]{32}")
_WHO = {"我": "我", "对方": "对方", "未知": "未知"}


def _safe(name: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    return re.sub(r"\s+", " ", clean)[:60] or "未命名"


def _stamp(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, _TZ)


def _load_messages(decrypted: Path, username: str) -> list[dict]:
    table = "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()
    messages: list[dict] = []
    for shard in sorted((decrypted / "message").glob("message_*.db")):
        if not shard.stem[len("message_"):].isdigit():
            continue
        connection = sqlite3.connect(shard)
        connection.row_factory = sqlite3.Row
        try:
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                continue
            senders = {
                int(row["rowid"]): str(row["user_name"])
                for row in connection.execute("SELECT rowid, user_name FROM Name2Id")
                if row["user_name"]
            }
            for row in connection.execute(
                f"SELECT local_id, server_id, local_type, sort_seq, real_sender_id, create_time, "
                f'status, message_content, compress_content, packed_info_data FROM "{table}"'
            ):
                item = dict(row)
                item["direction"] = direction_for_private_chat(
                    username, senders.get(int(row["real_sender_id"] or 0)), row["status"]
                )
                messages.append(item)
        finally:
            connection.close()
    messages.sort(
        key=lambda m: (int(m["create_time"] or 0), int(m["sort_seq"] or 0), int(m["local_id"] or 0))
    )
    return messages


def _load_voices(decrypted: Path, username: str) -> dict[int, bytes]:
    """server_id → SILK 数据（一条语音可能分多块，按 data_index 拼）。"""
    chunks: dict[int, list[tuple[int, bytes]]] = defaultdict(list)
    for path in sorted((decrypted / "message").glob("media_*.db")):
        connection = sqlite3.connect(path)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
            if not {"VoiceInfo", "Name2Id"} <= tables:
                continue
            found = connection.execute(
                "SELECT rowid FROM Name2Id WHERE user_name=?", (username,)
            ).fetchone()
            if not found:
                continue
            for svr_id, data_index, voice_data in connection.execute(
                "SELECT svr_id, data_index, voice_data FROM VoiceInfo WHERE chat_name_id=?",
                (found[0],),
            ):
                if voice_data:
                    chunks[int(svr_id)].append((int(data_index or 0), bytes(voice_data)))
        finally:
            connection.close()
    return {key: b"".join(part for _, part in sorted(parts)) for key, parts in chunks.items()}


def _packed_md5(packed: object) -> str | None:
    match = _MD5.search(bytes(packed)) if packed else None
    return match.group().decode() if match else None


def _stem(message: dict) -> str:
    when = _stamp(int(message["create_time"] or 0))
    return f"{when:%Y%m%d-%H%M%S}_{_WHO[message['direction']]}_{int(message['local_id'] or 0)}"


def _export_voices(
    messages: list[dict], voices: dict[int, bytes], out_dir: Path, work: Path,
    silk_python: str | None, ffmpeg: str | None,
) -> dict[str, object]:
    wanted = [m for m in messages if message_type_parts(m["local_type"])[0] == 34]
    result: dict[str, object] = {"messages": len(wanted), "exported": 0, "missing": 0, "format": "mp3"}
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[dict, Path]] = []
    for message in wanted:
        data = voices.get(int(message["server_id"] or 0))
        if not data:
            result["missing"] += 1
            continue
        done = out_dir / (_stem(message) + ".mp3")
        if done.is_file() and done.stat().st_size:
            message["media"] = done
            result["exported"] += 1
            continue
        silk = work / (_stem(message) + ".silk")
        silk.write_bytes(data)
        staged.append((message, silk))
    can_convert = bool(silk_python and Path(silk_python).is_file() and ffmpeg)
    if can_convert and staged:
        subprocess.run(
            [silk_python, str(Path(__file__).with_name("silk_decode.py")), str(work)],
            check=True, capture_output=True,
        )

        def to_mp3(pair: tuple[dict, Path]) -> bool:
            pcm = pair[1].with_suffix(".pcm")
            target = out_dir / (pair[1].stem + ".mp3")
            if not pcm.is_file():
                return False
            done = subprocess.run(
                [ffmpeg, "-loglevel", "error", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                 "-i", str(pcm), "-b:a", "32k", str(target)],
                capture_output=True,
            )
            return done.returncode == 0 and target.is_file()

        with ThreadPoolExecutor(max_workers=8) as pool:
            converted = list(pool.map(to_mp3, staged))
    else:
        converted = [False] * len(staged)
        if staged:
            result["format"] = "silk（未转码：缺 silk_python 或 ffmpeg）"
    raw_kept = 0
    for (message, silk), ok in zip(staged, converted):
        if ok:
            message["media"] = out_dir / (silk.stem + ".mp3")
        else:
            # 转不了的留原始 SILK，不丢数据
            target = out_dir / silk.name
            shutil.copy2(silk, target)
            message["media"] = target
            raw_kept += 1
        result["exported"] += 1
    result["kept_as_silk"] = raw_kept
    shutil.rmtree(work, ignore_errors=True)
    return result


def _wxgf_to_jpg(data: bytes, target: Path, ffmpeg: str | None, work: Path) -> bool:
    """wxgf 是微信自己的 HEVC 封装：从第一个起始码起交给 ffmpeg 取首帧。"""
    start = data.find(b"\x00\x00\x00\x01")
    if start < 0 or not ffmpeg:
        return False
    work.mkdir(parents=True, exist_ok=True)
    raw = work / (target.stem + ".hevc")
    raw.write_bytes(data[start:])
    done = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-y", "-f", "hevc", "-i", str(raw), "-frames:v", "1",
         str(target)],
        capture_output=True,
    )
    raw.unlink(missing_ok=True)
    return done.returncode == 0 and target.is_file()


def _export_images(
    messages: list[dict], attach: Path, out_dir: Path, work: Path, ffmpeg: str | None,
    account_id: str,
) -> dict[str, object]:
    wanted = [m for m in messages if message_type_parts(m["local_type"])[0] == 3]
    result: dict[str, object] = {
        "messages": len(wanted), "exported": 0, "thumbnail_only": 0, "missing": 0, "failed": 0,
    }
    if not wanted:
        return result
    files: dict[str, Path] = {}
    for path in attach.glob("*/Img/*.dat") if attach.is_dir() else []:
        files[path.name] = path
    out_dir.mkdir(parents=True, exist_ok=True)
    v2 = [path for path in files.values() if image_dat.is_v2(path.read_bytes()[:16])]
    xor_key = image_dat.find_xor_key([p for p in v2 if p.name.endswith("_t.dat")] or v2)
    aes_key = None
    if v2:
        samples = [
            sample for sample in (image_dat.aes_sample(path.read_bytes()) for path in v2[:3]) if sample
        ]
        # 先按账号 uin 推导（不碰进程内存）；推不出来再去微信内存里找
        aes_key = image_dat.derive_aes_key(
            account_id, samples, Path(os.environ.get("APPDATA", "")) / "Tencent" / "xwechat"
        ) or image_dat.find_aes_key(samples)
        result["image_key_found"] = aes_key is not None
    for message in wanted:
        md5 = _packed_md5(message["packed_info_data"])
        local = f"{int(message['local_id'] or 0)}_{int(message['create_time'] or 0)}"
        source, thumb = None, False
        for name, is_thumb in (
            (f"{md5}_h.dat", False), (f"{md5}.dat", False), (f"{local}_h.dat", False),
            (f"{local}.dat", False), (f"{md5}_t.dat", True), (f"{local}_t.dat", True),
        ):
            if name in files:
                source, thumb = files[name], is_thumb
                break
        if source is None:
            result["missing"] += 1
            continue
        try:
            plain = image_dat.decrypt_dat(source.read_bytes(), aes_key, xor_key)
            ext = image_dat.image_ext(plain)
            if ext is None:
                raise ValueError("解密结果不是图片")
        except ValueError:
            result["failed"] += 1
            continue
        stem = _stem(message) + ("_缩略图" if thumb else "")
        target = out_dir / (stem + ext)
        if ext == ".wxgf":
            target = out_dir / (stem + ".jpg")
            if not _wxgf_to_jpg(plain, target, ffmpeg, work):
                target = out_dir / (stem + ".wxgf")
                target.write_bytes(plain)
        else:
            target.write_bytes(plain)
        message["media"] = target
        result["exported"] += 1
        result["thumbnail_only"] += int(thumb)
    return result


def _export_videos(messages: list[dict], video_root: Path, out_dir: Path) -> dict[str, object]:
    wanted = [m for m in messages if message_type_parts(m["local_type"])[0] == 43]
    result: dict[str, object] = {"messages": len(wanted), "exported": 0, "missing": 0}
    if not wanted:
        return result
    out_dir.mkdir(parents=True, exist_ok=True)
    for message in wanted:
        md5 = _packed_md5(message["packed_info_data"])
        month = f"{_stamp(int(message['create_time'] or 0)):%Y-%m}"
        candidates = (
            [video_root / month / f"{md5}.mp4", video_root / month / f"{md5}_raw.mp4"]
            + sorted(video_root.glob(f"*/{md5}.mp4")) + sorted(video_root.glob(f"*/{md5}_raw.mp4"))
            if md5 else []
        )
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            result["missing"] += 1
            continue
        target = out_dir / (_stem(message) + ".mp4")
        if not (target.is_file() and target.stat().st_size == source.stat().st_size):
            shutil.copy2(source, target)
        message["media"] = target
        result["exported"] += 1
    return result


def _voice_seconds(message: dict) -> str:
    text = decode_message_content(message["message_content"] or message["compress_content"])
    match = re.search(r'voicelength\s*=\s*"(\d+)"', text)
    return f"{round(int(match.group(1)) / 1000)}″" if match else ""


def _render_html(name: str, username: str, messages: list[dict], page: Path) -> None:
    cards = []
    for message in messages:
        base, _ = message_type_parts(message["local_type"])
        direction = message["direction"]
        css = "mine" if direction == "我" else "theirs" if direction == "对方" else "unknown"
        content = message["message_content"]
        if content in (None, "", b""):
            content = message["compress_content"]
        label, text = summarize_content(message["local_type"], content)
        media = message.get("media")
        if media is not None:
            src = html.escape(
                Path("..", *media.relative_to(page.parent.parent).parts).as_posix(), quote=True
            )
            if base == 34 and media.suffix == ".mp3":
                body = (f'<audio controls preload="none" src="{src}"></audio>'
                        f'<span class="len">{_voice_seconds(message)}</span>')
            elif base == 3 and media.suffix != ".wxgf":
                body = f'<a href="{src}" target="_blank"><img loading="lazy" src="{src}"></a>'
            elif base == 43:
                body = f'<video controls preload="none" src="{src}"></video>'
            else:
                body = f'<a href="{src}" target="_blank">[{label}] {html.escape(media.name)}</a>'
        elif base in (3, 34, 43):
            body = f"[{label}]（本机没有这个文件）"
        elif base == 47:
            body = "[动画表情]"
        else:
            body = html.escape(text).replace("\n", "<br>")
        when = _stamp(int(message["create_time"] or 0))
        sender = "我" if direction == "我" else name if direction == "对方" else "未知"
        cards.append(
            f'<article class="message {css}"><div class="meta">{when:%Y-%m-%d %H:%M:%S} · '
            f'{html.escape(sender)} · {label}</div><div class="bubble">{body}</div></article>'
        )
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - 微信聊天记录（含媒体）</title><style>
body{{margin:0;background:#f4f6f8;color:#202124;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}}
header{{position:sticky;top:0;z-index:2;background:#17324d;color:#fff;padding:20px max(20px,calc((100% - 900px)/2));box-shadow:0 2px 8px #0002}}
h1{{font-size:22px;margin:0 0 4px}}.sub{{opacity:.8;font-size:13px}}main{{max-width:900px;margin:0 auto;padding:24px 18px 50px}}
.message{{margin:14px 0;display:flex;flex-direction:column;align-items:flex-start}}.message.mine{{align-items:flex-end}}.meta{{font-size:12px;color:#6b7280;margin:0 8px 5px}}
.bubble{{max-width:78%;background:#fff;border:1px solid #e3e7eb;border-radius:14px;padding:10px 13px;overflow-wrap:anywhere;box-shadow:0 1px 2px #0000000d}}
.mine .bubble{{background:#dff4d1;border-color:#c7e7b5}}.unknown .bubble{{background:#fff7d6}}
.bubble img,.bubble video{{display:block;max-width:min(360px,100%);max-height:480px;border-radius:8px}}
.bubble audio{{height:34px;vertical-align:middle;max-width:100%}}.len{{margin-left:8px;color:#6b7280;font-size:13px}}
footer{{text-align:center;color:#8a939d;font-size:12px;padding:24px}}
</style></head><body><header><h1>{title}</h1><div class="sub">微信号：{username} · 共 {total} 条 · 时间为北京时间</div></header>
<main>{cards}</main><footer>由本地微信数据库整理生成 · 内容未上传</footer></body></html>""".format(
            title=html.escape(name), username=html.escape(username), total=len(messages),
            cards="\n".join(cards),
        ),
        encoding="utf-8",
    )


def export_media(run_root: Path, to: Path | None, account_dir: Path | None = None) -> dict[str, object]:
    if to is not None:
        ensure_outside_skill_root(to, "媒体导出目录")
    state = json.loads((run_root / "run-state.json").read_text(encoding="utf-8"))
    watched = [str(item) for item in state.get("watchlist_wxids") or []]
    if state.get("selection_mode") != SELECTION_MODE or not watched:
        raise RuntimeError("本 skill 只导出用户点名的人：请先运行 select_people.py")
    decrypted = run_root / "private" / "decrypted"
    if not decrypted.is_dir():
        raise RuntimeError("明文库已清理：媒体导出要在 finalize 的 purge 之前跑，或从快照重来")
    published = to or Path(str(state.get("published_to") or ""))
    if not published.is_dir():
        raise RuntimeError("找不到发布目录：先跑 publish.py，或用 --to 指定")
    if account_dir is None:
        account = authorize_account(
            discover_accounts([*search_roots(), *default_search_roots()]),
            str(state["account_id"]),
        )
        account_dir = account.db_storage.parent
    registry = load_registry()
    silk_python = registry.get("silk_python")
    ffmpeg = shutil.which("ffmpeg")
    contacts = _contact_map(decrypted / "contact" / "contact.db")
    work = run_root / "private" / "media_tmp"

    people = []
    for username in watched:
        contact = contacts.get(username, {})
        name = display_name(
            username, contact.get("remark"), contact.get("nick_name"), contact.get("alias")
        )
        folder = published / "媒体" / _safe(name)
        messages = _load_messages(decrypted, username)
        chat_hash = hashlib.md5(username.encode("utf-8")).hexdigest()
        voice = _export_voices(
            messages, _load_voices(decrypted, username), folder / "语音", work / "voice",
            silk_python, ffmpeg,
        )
        image = _export_images(
            messages, account_dir / "msg" / "attach" / chat_hash, folder / "图片", work, ffmpeg,
            str(state["account_id"]),
        )
        video = _export_videos(messages, account_dir / "msg" / "video", folder / "视频")
        page = published / "聊天记录_含媒体" / f"{_safe(name)}.html"
        _render_html(name, username, messages, page)
        people.append(
            {"显示名": name, "微信号": username, "消息数": len(messages), "语音": voice,
             "图片": image, "视频": video, "含媒体页面": str(page)}
        )
    shutil.rmtree(work, ignore_errors=True)
    summary = {"status": "ok", "published_to": str(published), "people": people}
    (published / "媒体导出摘要.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="导出点名的人的语音、图片、视频，并生成带媒体的聊天页面（发布之后、清明文之前跑）"
    )
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--to", type=Path, help="发布目录；缺省用 run-state 的 published_to")
    parser.add_argument("--purge-workspace", action="store_true", help="跑完后清掉快照和明文库")
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    try:
        result = export_media(run_root, args.to)
        if args.purge_workspace:
            result["purged"] = _purge_workspace(run_root)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
