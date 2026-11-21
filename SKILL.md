---
name: 微信指定好友聊天导出
description: 只导出用户点名的人的微信一对一聊天记录（Windows 微信 4.x，本机）。用户说要谁就只读谁，没点名的会话不读正文、名字不落盘。触发：「导出我和 XX 的聊天记录」「把 XX 的微信聊天拉下来」「更新 XX 的聊天记录」「更新关注名单的聊天」「我要 XX 和 YY 的聊天记录」。流程：快照解密 → 按点名匹配会话元数据（零正文）→ 重名/模糊的退回用户定 → 只导出点到的人 → 对账打包 → 解压到用户指定目录 → 可选导出图片/语音/视频 → 清明文。全程本机，不联网。
---

# 微信指定好友聊天导出（点名版）

## 特点

| 特点 | 说明 |
|---|---|
| 点名才导 | `select_people.py` 按用户点的名字匹配会话元数据，没点名的人不读正文、不落盘 |
| 点名闸门 | `run_export.py` 只认 `select_people.py` 生成的清单；清单里有点名范围外的行就整体拒绝 |
| 只解密要用的库 | 联系人、会话、一对一消息分库、语音库。朋友圈、收藏、公众号消息等不解密 |
| 媒体导出 | `export_media.py` 导出点名的人的语音（转 mp3）、图片（解密 .dat）、视频，外加一个带媒体的聊天页面 |
| 关注名单 | `watchlist.json` 存下点过名并确认的人，下次「更新关注名单」直接复用 |
| 自定义数据目录 | 微信设置里改过存储位置的，在 `accounts.json` 的 `search_roots` 登记 |

所有命令在 skill 根目录（`%USERPROFILE%\.claude\skills\微信指定好友聊天导出`）下跑，用 `python -I`。

## 首次使用

1. 装依赖：`python -m pip install pycryptodomex zstandard openpyxl`（`openpyxl` 可选，缺了索引降级为 CSV）。
2. 复制 `accounts.example.json` 为 `accounts.json`，按本机情况填：
   - `search_roots`：微信数据根目录（目录名一般是 `xwechat_files`）。在微信「设置 → 文件管理」能看到；用默认位置的可以留空数组。
   - `accounts`：别名 → 账号 ID。不知道账号 ID 就先跑 `python -I scripts/preflight.py`，它会列出本机所有账号 ID（形如 `wxid_xxx_xxxx`）。
   - `output_root`：运行目录，必须在微信数据目录和 skill 目录之外。`publish_dir`：导出结果默认放哪，可不填，每次用 `--to` 指定；同样不能放在 skill 目录内。
   - `silk_python`：只有要把语音转 mp3 才需要。单独建一个 venv 装 `pilk`，填它的 `python.exe` 路径；PATH 里还要有 ffmpeg。
3. `accounts.json` 和 `watchlist.json` 含本人账号和朋友的微信号，已在 `.gitignore` 里，不要提交、不要外传。运行目录或发布目录落在 skill 目录内时，`prepare_snapshot.py` / `publish.py` 直接报错退出。

## 三道门（不可越过）

1. **账号门**：只处理用户点名的账号。别名在 `accounts.json` 里唯一对应一个 account_id 即视为授权，向用户报出这个 ID；没登记的，预检后把账号 ID 原样列出，让用户回复准确 ID。不按目录大小、修改时间猜。用户没说哪个号时，问一次。
2. **点名门**：只导出用户这次点名的人，或用户明确说「关注名单里的人」。不替用户加人，不按「可能是朋友」推断，不做全量导出。
3. **只看点到的人**：`select_people.py` 的输出里只有点名命中的候选，可以报给用户核对；其余联系人只报总数。不自己去查解密库里的联系人表，不读正文，不报密钥。导出的聊天内容用户没让看就不打开。

## 流程

1. **拿到名单**：用户给名字（备注名、昵称或微信号都行）。没给就问「要谁的」，不往下跑。
2. **预检（只读）**：`python -I scripts/preflight.py`。看 `weixin_version`、账号列表、缺失依赖。微信必须登录着目标账号且全程保持运行。
3. **快照 + 解密**：`python -I scripts/prepare_snapshot.py --account-id <别名或ID>`。要读微信进程内存取密钥，耗时数分钟，用后台跑。记下 `run_root`。
4. **点名**：`python -I scripts/select_people.py --run-root <run_root> --name "<名字>" [--name ...] [--wxid <微信号>] [--from-watchlist]`
   - `status: awaiting_export`：每个点名都精确且唯一命中。把 `selected` 里的显示名、消息数、起止时间报给用户，直接进第 5 步。
   - `status: needs_attention`（退出码 2）：什么都没写。把 `to_confirm`（重名、模糊命中）的候选和 `not_found` 的名字报给用户定，定下来后用 `--wxid <微信号>` 精确重跑；用户说不要的人直接去掉。`to_confirm` 里只有数量没有候选，说明点名太宽，请用户给更完整的名字。
   - 模糊命中即使只有一个候选也要用户确认，不自动选。
   - `--from-watchlist`：用户说「更新关注名单 / 上次那几个人」时用。
5. **导出**：`python -I scripts/run_export.py --run-root <run_root>`
6. **索引表**：`python -I scripts/build_index.py --run-root <run_root>`
7. **对账打包**：`python -I scripts/finalize_delivery.py --run-root <run_root>`。用户只要文字时加 `--purge-workspace` 当场清明文；还要图片/语音/视频时先不加，留到第 9 步清（媒体导出要用明文库）。明文库含全部私聊，不只是点名的人，流程结束前必须清掉。
8. **发布**：`python -I scripts/publish.py --run-root <run_root> --to <发布目录>`。发布目录由用户指定，没说就问一次；`accounts.json` 登记了 `publish_dir` 才能省略 `--to`。解压到 `<发布目录>\聊天导出_YYYYMMDD\`：`聊天索引.xlsx`（缺 `openpyxl` 时为 `聊天索引.csv`）、`聊天记录_HTML\`、`聊天记录_CSV\`、`导出摘要.json`、`README.txt`。同目录下上一版（`聊天导出_*`）自动挪进 `_archive\`。
9. **媒体（用户要图片/语音/视频时）**：`python -I scripts/export_media.py --run-root <run_root> --purge-workspace`。在发布目录里生成 `媒体\<显示名>\语音|图片|视频\`（文件名 = 北京时间_我或对方_消息ID）和 `聊天记录_含媒体\<显示名>.html`（语音可点播、图片视频内嵌），并写 `媒体导出摘要.json`。可重复跑，已导出的文件跳过。
   - 语音：`media_N.db` 里的 SILK → mp3。要 `accounts.json` 的 `silk_python`（装了 `pilk` 的独立 venv）和 PATH 里的 ffmpeg；缺了就原样留 `.silk`。
   - 图片：解密 `msg\attach\<md5(微信号)>\` 下的 `.dat`，优先原图；只有缩略图的，文件名带「_缩略图」。V2 密钥按 `MD5(uin + 微信号)` 前 16 位推导（uin 取自 `%APPDATA%\Tencent\xwechat` 下各 `kvcomm` 目录的文件名），推不出来才扫微信内存。
   - 视频：`msg\video\` 下的 mp4 原样拷贝。
   - 用户没在这台电脑上点开过的图片/视频，本机没有文件，摘要里计入 `missing`，如实报。
   - 动画表情、文件附件目前不导出。
10. **汇报**：终态 complete 且对账、ZIP CRC 通过才算完成。报：导出了谁（会话数、消息数）、没导出的私聊会话数、媒体各类的导出数和缺失数、发布目录绝对路径。确认 `source_copy` 和 `private` 已清。

## 关注名单

- `watchlist.json`（skill 根目录，不入 git）：账号 ID → 点过名的人（微信号、当时的叫法、加入日期）。`select_people.py` 成功后自动追加。
- 移除某人：删掉 `watchlist.json` 里对应条目。
- 同一个朋友有两个微信号：两个都用 `--wxid` 点名。

## 失败处理

- 读微信内存取密钥属于非常规操作。导出后如果遇到微信网络异常、登录异常，先停手，不再碰微信进程。
- 第 3 步（解密并通过 SQLite 校验）已在微信 4.1.x、4.2.0.13 上验证。微信再升级后第 3 步失败就如实报，不绕过检查。
- `validated keys do not cover all databases ... missing: <库>`：先确认登录的就是该账号、聊天列表已加载（把会话列表往下翻一翻），再新建运行重跑。
- 缺 `pycryptodomex` / `zstandard` / `openpyxl`：说明用途，用户同意再装。`openpyxl` 缺失会降级为 CSV 索引，不阻塞。
- 版本不是 4.x、核心库缺失、SQLite 校验失败、数量不守恒：停止并如实报告。不交部分结果。
- 失败的运行目录里若残留 `source_copy`（加密快照）或 `private`（明文库），告诉用户可以删，不要自己删。
- **导完后要去掉某人**：把 `会话清单.csv` 里那一行「是否导出」列的 Y 清掉，跑 `python -I scripts/resync_delivery.py --run-root <run_root>`，它直接在发布目录里删掉这个会话并重写摘要和索引。只能删人；要加人得从第 3 步重来（明文库已清）。
- 要重跑第 5 步：先把 `<run_root>\delivery` 挪走；已 purge 的运行只能从第 3 步重来。

## 目录约定

- 运行目录：`accounts.json` 里该账号的 `output_root`（`<output_root>\<wxid>\<时间>-run\`），没填时默认 `%LOCALAPPDATA%\WeChatChatExport\runs`。必须在微信数据目录和 skill 目录之外。跑完只剩 `会话清单.csv`（仅点名的人）、`run-state.json`、`delivery\索引数据.json`。
- 解密明文库一律 purge，不留、不归档。
- 微信数据目录只读，不改不删。

## 维护

- 改代码后跑 `python -B -m pytest -p no:cacheprovider tests -q`（当前 72 条）。`export_media.py`、`image_dat.py` 还没有单元测试，目前只靠实机验证（语音、图片、视频逐个用 ffprobe 校验）。
- 导出时间统一按北京时间（UTC+8）。
- 账号别名、数据根目录、运行与发布目录只改 `accounts.json`。
- `accounts.json` 含本机真实账号 ID，`watchlist.json` 含朋友的微信号，都不入 git，不要推到远端。
- 兼容性与安全细则：`references/compatibility-and-safety.md`；交付物契约：`references/output-contract.md`。
