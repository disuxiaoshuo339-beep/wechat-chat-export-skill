"""把目录里的 .silk 解成同名 .pcm（16 位单声道 24 kHz）。
由 export_media.py 用装了 pilk 的那个 Python 解释器调用（accounts.json 的 silk_python）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pilk

ok = failed = 0
for source in sorted(Path(sys.argv[1]).glob("*.silk")):
    try:
        pilk.decode(str(source), str(source.with_suffix(".pcm")), pcm_rate=24000)
        ok += 1
    except Exception:  # 单条坏语音不拖垮整批
        failed += 1
print(json.dumps({"decoded": ok, "failed": failed}))
