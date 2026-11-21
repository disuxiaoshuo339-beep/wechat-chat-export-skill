# 兼容性与安全边界

- 目标环境：Windows、支持本地命令行的 AI 编码助手（如 Claude Code）、正在运行的微信 4.x。
- Python 3.11+；需要 `pycryptodomex` 与 zstd 支持（Python 3.14 自带 `compression.zstd`，否则用 `zstandard`）；`openpyxl` 可选，缺失时索引降级为 CSV。
- 采用运行中微信进程和本地数据库的只读快照；源目录不修改、不删除、不覆盖。
- 账号授权必须精确到预检列出的账号 ID。发现多个账号时尤其不能代选。
- 密钥仅在内存中短暂存在，使用后清零；不得写入文件、聊天回复、日志或 ZIP。
- 输出和临时工作目录必须位于微信数据目录之外，也不能在 skill 目录内（`prepare_snapshot.py`、`publish.py` 检测到会报错退出）。
- 仅支持经校验的 SQLCipher 页面参数和当前 WAL 盐；过期或未提交 WAL 帧不得合并。
- 默认排除群聊、公众号和系统账号；`@openim` 私聊保留。
- **点名闸门**：只导出用户点名的人。`select_people.py` 按点名匹配会话元数据（不 SELECT 任何消息正文字段），只有精确且唯一命中的人写进会话清单；`run_export.py` 只认它生成的清单，清单外的会话在发出正文查询之前即被跳过，清单里出现点名范围外的行则整体拒绝。
- **只看点到的人**：脚本输出里只有点名命中的候选，其余联系人只有总数；`会话清单.csv` 也只含点名的人。AI 不自行查询解密库里的联系人表。
- **解密范围**：只解密联系人、会话、一对一消息分库和语音库（`contact/contact.db`、`session/session.db`、`message/message_N.db`、`message/media_N.db`）；其余库只留在加密快照里，不产生明文。
- **媒体**：`export_media.py` 只处理本轮点名的微信号；微信的 `msg` 目录只读；图片密钥只在内存里用，不写文件。
- **明文清理**：`source_copy`（加密快照）与 `private`（明文库，含全部私聊而不只是点名的人）在交付完成后由 `finalize_delivery.py --purge-workspace` 删除。
- 所有文件都在本机处理。禁止调用外部上传、云端分析或付费 API。
- 安装任何第三方依赖前必须获得用户许可。
