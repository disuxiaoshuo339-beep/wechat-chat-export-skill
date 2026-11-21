from __future__ import annotations

import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = SKILL_ROOT / "accounts.json"


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    if not path.is_file():
        return {"accounts": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def search_roots(registry: dict | None = None) -> list[Path]:
    """accounts.json 里登记的微信数据根目录（微信设置里改过存储位置时，默认位置找不到账号）。"""
    registry = registry if registry is not None else load_registry()
    return [Path(item) for item in registry.get("search_roots", []) if Path(item).is_dir()]


def resolve_account(value: str, registry: dict | None = None) -> tuple[str, dict]:
    """别名或账号 ID → (account_id, 登记项)。未登记的原样返回、登记项为空。"""
    registry = registry if registry is not None else load_registry()
    accounts = registry.get("accounts", {})
    if value in accounts:
        entry = accounts[value]
        return entry["account_id"], {"alias": value, **entry}
    for alias, entry in accounts.items():
        if entry.get("account_id") == value:
            return value, {"alias": alias, **entry}
    return value, {}



def ensure_outside_skill_root(path: Path, label: str, skill_root: Path = SKILL_ROOT) -> Path:
    """运行目录、发布目录含聊天明文，不许落在 skill 根目录（git 仓库）里，免得被误提交。"""
    resolved = Path(path).resolve()
    root = skill_root.resolve()
    if resolved == root or root in resolved.parents:
        raise RuntimeError(
            f"{label} 不能放在 skill 目录内：{resolved}；请改到 skill 目录（{root}）之外"
        )
    return resolved
