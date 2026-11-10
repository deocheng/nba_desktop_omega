# DET 金标夹具（冻结快照）

`tests/test_hof_exec_offline.py` 与 `tests/test_transactions_offline.py` 的
「解析器 vs 手工核对金标」回归输入。

## 为什么是快照而不是实时抓取目录

本机抓取缓存 `det2026_br/` 是指向外置盘的**符号链接**
（`det2026_br -> /Volumes/12T/NBA/det2026_br`）：

* 符号链接下的文件**无法进入 git**（`git add` 报 "pathspec is beyond a symbolic link"）；
* 该目录有 2400+ 个抓取页面（约 400 MB），全量入库不可接受；
* 结果：CI 上 `det2026_br/` 根本不存在 → 两个测试在 **collection 阶段**就
  `FileNotFoundError` → 整个 test job 直接崩（本地永远看不到，因为本机有该目录）。

因此把**测试真正用到的 6 个文件**冻结进本目录（736 KB）：

| 文件 | 作用 |
| --- | --- |
| `DET_hof.html` | BR 名人堂页原始 HTML（解析输入） |
| `DET_executives.csv` | 球队高管金标（手工核对，22 条任期） |
| `DET_executives.html` | BR 高管页原始 HTML（解析输入） |
| `DET_hof_players.json` | 名人堂金标（118 条 (赛季,球员)、23 位球员） |
| `DET_2026_transactions_raw.html` | BR 交易页原始 HTML（解析输入） |
| `DET_2026_transactions_verbatim.txt` | 交易金标（35 行，逐行 (日期,描述)） |

## 权威口径

* **金标（gold）= 唯一断言基准**：`DET_hof_players.json` / `DET_executives.csv` /
  `DET_2026_transactions_verbatim.txt` 是人工核对结果，解析器必须逐字复现它们。
* **原始 HTML = 被测输入**：仅是喂给解析器的字节快照，本身不是基准。
* 快照一旦入库即**冻结**：本地与 CI 读同一份字节 → 同一断言、同一结果，
  不因本机重新抓取而漂移。

## 如何刷新快照

本机重新抓取 DET 页面后（如 `det2026_br/` 内容更新）：

```bash
cd /Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
for f in DET_hof.html DET_executives.html DET_hof_players.json \
         DET_executives.csv DET_2026_transactions_raw.html \
         DET_2026_transactions_verbatim.txt; do
  cp -p "/Volumes/12T/NBA/det2026_br/$f" "tests/fixtures/det2026_br/$f"
done
```

刷新后必须让金标断言仍成立（条数/逐行相等）——若金标本身变了，
说明「手工核对结果」变了，需先确认金标变更再更新快照。
