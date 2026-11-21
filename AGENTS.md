# AGENTS.md

本仓库是一个导出 Windows 微信 4.x 指定好友一对一聊天记录的工具（Claude Code skill，Codex 等其他 AI 编码助手同样可用）。

开始任何操作前，先完整阅读 `SKILL.md`，严格按其中的「三道门」和流程执行：

- 先跑只读预检：`python -I scripts/preflight.py`，把列出的账号 ID 报给用户，由用户确认是哪一个，不代选。
- 只导出用户点名的人；没点名就问，不做全量导出。
- 聊天正文、联系人、数据库、密钥、日志、导出结果都只留在本机：不发到对话里，不提交 git，不上传任何地方。
- 不执行 `git add` / `git commit` / `git push`。
- 预检找不到账号时：让用户在微信「设置 → 文件管理」里看存储位置，把该目录（或其下的 `xwechat_files`）填进 `accounts.json` 的 `search_roots`（从 `accounts.example.json` 复制），或用 `--root <目录>` 重跑预检。
