# 输出契约

成功交付 ZIP 只允许包含：

- `聊天索引.xlsx`（无 `openpyxl` 时为 `聊天索引.csv`，二者只出现一个）
- `聊天记录_HTML/*.html`
- `聊天记录_CSV/*.csv`
- `导出摘要.json`
- `README.txt`

不得包含数据库、WAL/SHM、密钥文件、进程转储、源快照、私有工作目录、日志、测试缓存，也不得包含 `索引数据.json`、`会话清单.csv`、`run-state.json`、`source-manifest.csv`、`final-result.json` 这些中间文件。`会话清单.csv` 在本版只含点名的人，仍属中间文件，不进交付包。

验收条件：

- 索引表行数 = 用户点名并确认的会话数。
- HTML 数 = CSV 数 = 点名会话数。
- 每个会话的消息数与其 CSV 数据行数一致。
- 导出消息总数 = 我发送 + 对方发送 + 未知方向。
- 点名会话数 + 筛除会话数 = 库中一对一私聊会话总数（`导出摘要.json` 里的 `private_conversations` + `screened_out_conversations`）。
- ZIP 文件清单通过禁入检查并可完整 CRC 解压测试。
