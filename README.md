# 微信指定好友聊天导出（Claude Code skill）

只导出你点名的人的微信一对一聊天记录。Windows 微信 4.x，全程本机处理，不联网。

## 安装

```powershell
git clone https://github.com/disuxiaoshuo339-beep/wechat-chat-export-skill.git "$env:USERPROFILE\.claude\skills\微信指定好友聊天导出"
cd "$env:USERPROFILE\.claude\skills\微信指定好友聊天导出"
python -m pip install pycryptodomex zstandard openpyxl
copy accounts.example.json accounts.json   # 然后按 SKILL.md「首次使用」填
```

重开 Claude Code 后直接说：「导出我和 XX 的聊天记录」。

### 用 Codex 等其他 AI 助手

克隆到任意目录，在 AI 助手里打开这个目录作为项目，然后发：

```text
请先阅读根目录 AGENTS.md 和 SKILL.md，按其中流程帮我导出本机微信里和 XX 的聊天记录，现在先只做只读预检。
账号由我确认；聊天内容、联系人、数据库、密钥和导出结果都不要发到对话或 GitHub；不要执行 git add/commit/push。
```

### 预检找不到账号？

预检会自动读取微信记录的存储位置（`%APPDATA%\Tencent\xwechat\config\*.ini`）。仍找不到时，在微信「设置 → 文件管理」看存储位置，把它填进 `accounts.json` 的 `search_roots`，或运行 `python -I scripts/preflight.py --root "<存储位置>"`。

## 使用前提

- Windows，微信 4.x 已登录目标账号，导出期间保持运行。
- Python 3.11+。
- 只能导出本机微信里的聊天；没在这台电脑上打开过的图片、视频导不出来。

## 声明

- 本项目不是微信或腾讯官方产品，与其无关联。
- 只用于导出你本人账号、本人电脑上的聊天记录。导出他人聊天内容前，请确认符合当地法律和对方意愿。
- 读取微信进程内存取密钥属于非常规操作，可能违反微信软件许可协议，风险由使用者自行承担。
- 代码使用 [MIT 许可证](LICENSE)，按现状提供，不作任何保证。

## 注意

- `accounts.json`、`watchlist.json` 和导出的聊天记录都含个人信息，不要提交、不要外传。`accounts.json`、`watchlist.json` 已在 `.gitignore` 里；运行目录和发布目录不允许放在 skill 目录内（`prepare_snapshot.py`、`publish.py` 会报错退出），`.gitignore` 另外兜底排除了导出产物和中间文件（`聊天导出_*/`、`_archive/`、`*-run*/`、`*.zip`、`会话清单.csv`、`*.db` 等）。
- 流程、三道门、失败处理见 `SKILL.md`。
