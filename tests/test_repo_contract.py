from __future__ import annotations

import re
from pathlib import Path


# skill 根目录即仓库根目录。accounts.json / watchlist.json 是本机登记，不入 git，
# 本测试只扫 .md/.py/.yaml，不读它们。
SKILL = Path(__file__).resolve().parents[1]
PACKAGE = SKILL


def test_skill_has_entry_scripts_and_no_account_data():
    assert (SKILL / "SKILL.md").is_file()
    assert (SKILL / "scripts" / "run_export.py").is_file()
    assert (SKILL / "scripts" / "prepare_snapshot.py").is_file()
    assert (SKILL / "scripts" / "select_people.py").is_file()
    # 通用规则：真实微信号形如 wxid_ + 16 位以上小写字母数字，
    # 测试夹具用的短名（wxid_friend / wxid_company 等）不会命中。
    real_account_pattern = re.compile(r"wxid_[0-9a-z]{16,}")
    for path in PACKAGE.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".py", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not real_account_pattern.search(text), f"疑似真实微信号泄漏：{path}"
    assert not any(path.name.lower() == "keys.json" for path in PACKAGE.rglob("*"))


def test_package_has_no_database_or_process_dump_files():
    forbidden = {".db", ".db-wal", ".db-shm", ".dmp"}
    files = [path for path in PACKAGE.rglob("*") if path.is_file()]
    assert not [path for path in files if any(path.name.lower().endswith(x) for x in forbidden)]


def test_gitignore_covers_account_files_and_export_artifacts():
    patterns = {
        line.strip()
        for line in (SKILL / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    required = {
        "accounts.json", "watchlist.json", ".env",
        "聊天导出_*/", "_archive/", "*-run*/", "*.zip", "聊天记录_*/", "媒体/",
        "会话清单.csv", "run-state.json", "final-result.json", "source-manifest.csv",
        "*.db", "*.db-wal", "*.db-shm", "*.silk",
    }
    assert not required - patterns, sorted(required - patterns)
