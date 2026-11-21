from __future__ import annotations

from pathlib import Path

import pytest

from wechat_export.discovery import (
    AccountCandidate,
    authorize_account,
    discover_accounts,
)


def test_discovers_accounts_by_db_storage_not_folder_prefix(tmp_path):
    account = tmp_path / "custom-account_ab12"
    message = account / "db_storage" / "message"
    message.mkdir(parents=True)
    (message / "message_0.db").write_bytes(b"x" * 4096)

    found = discover_accounts([tmp_path])

    assert [item.account_id for item in found] == ["custom-account_ab12"]
    assert found[0].has_message_db


def test_discovery_deduplicates_the_same_resolved_account(tmp_path):
    account = tmp_path / "xwechat_files" / "wxid_fixture_ab12"
    (account / "db_storage" / "message").mkdir(parents=True)
    (account / "db_storage" / "message" / "message_0.db").write_bytes(b"x" * 4096)

    found = discover_accounts([tmp_path, tmp_path / "xwechat_files"])

    assert len(found) == 1


def test_authorization_requires_exact_discovered_account(tmp_path):
    candidate = AccountCandidate(
        account_id="wxid_fixture_ab12",
        db_storage=tmp_path / "db_storage",
        weixin_version="4.1.13.6",
        has_contact_db=True,
        has_session_db=True,
        has_message_db=True,
        process_count=1,
    )

    assert authorize_account([candidate], "wxid_fixture_ab12") == candidate
    with pytest.raises(ValueError, match="explicitly discovered"):
        authorize_account([candidate], "wxid_other")


def test_authorization_rejects_ambiguous_duplicate_identifiers(tmp_path):
    candidates = [
        AccountCandidate("same", tmp_path / "a" / "db_storage"),
        AccountCandidate("same", tmp_path / "b" / "db_storage"),
    ]

    with pytest.raises(ValueError, match="not unique"):
        authorize_account(candidates, "same")


def test_configured_storage_roots_reads_custom_location(tmp_path):
    from wechat_export.discovery import configured_storage_roots

    storage = tmp_path / "自定义存储"
    account = storage / "xwechat_files" / "wxid_fixture_ab12" / "db_storage" / "message"
    account.mkdir(parents=True)
    (account / "message_0.db").write_bytes(b"x" * 4096)
    config = tmp_path / "config"
    config.mkdir()
    (config / "abc.ini").write_bytes(str(storage).encode("utf-8"))
    (config / "noise.ini").write_bytes(b"not a path")
    (config / "missing.ini").write_bytes(str(tmp_path / "nope").encode("utf-8"))

    roots = configured_storage_roots(config)

    assert roots == [storage / "xwechat_files", storage]
    found = discover_accounts(roots)
    assert [item.account_id for item in found] == ["wxid_fixture_ab12"]


def test_configured_storage_roots_tolerates_missing_dir(tmp_path):
    from wechat_export.discovery import configured_storage_roots

    assert configured_storage_roots(tmp_path / "absent") == []
