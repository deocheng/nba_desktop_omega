# 测试夹具（冻结快照）

`tests/fixtures/` 下是**入库的**测试输入：解析器/回归逻辑的唯一字节输入。

## 为什么要有这一层

本机的真实抓取产物都放在**不入库**的位置：

| 本机目录 | 实际形态 | git 状态 |
| --- | --- | --- |
| `det2026_br/` | 符号链接 → `/Volumes/12T/NBA/det2026_br`（2400+ 页 / ~400 MB） | 符号链接下的文件**无法入库**（`git add` 报 "pathspec is beyond a symbolic link"） |
| `raw_archive/` | BR/ESPN 原始落盘（~17 GB+） | `.gitignore` 明确排除 |

后果：直接引用这些路径的测试**在本地全绿、在 CI 全红**（CI 上目录不存在），
且报错常出现在 **collection 阶段**（模块顶层 `open(...)`），会直接中断整个
test job —— 本地永远看不到。

解法：把测试**真正用到**的文件冻结成快照入库，目录镜像原归档结构，
来源与刷新方式逐目录记录（见 `det2026_br/README.md`）。

## 目录

| 子目录 | 来源 | 体积 | 被谁用 |
| --- | --- | --- | --- |
| `det2026_br/` | `det2026_br/`（外置盘符号链接目标） | ~736 KB | `test_hof_exec_offline.py`、`test_transactions_offline.py`、`test_team_pages_offline.py` |
| `br_players/` | `raw_archive/br_players/` | ~760 KB | `test_br_player_404.py`、`test_br_player_onoff.py` |

## 铁律

1. **快照即契约**：入库后**冻结**。本地与 CI 读同一份字节 → 同一断言、同一结果，
   不因本机重新抓取而漂移。
2. **金标优先**：人工核对结果（`DET_hof_players.json` / `DET_executives.csv` /
   `DET_2026_transactions_verbatim.txt`）才是断言基准；原始 HTML 只是被测输入。
3. **只拷必要文件**：只冻结被断言直接读到的文件，不整目录打包
   （原始页面上千个、单个 ~160–300 KB）。
4. **刷新需复核**：重新抓取后刷新快照，必须确认金标断言仍成立；
   金标本身变了说明「人工核对结果」变了，需先确认金标变更再更新快照。
