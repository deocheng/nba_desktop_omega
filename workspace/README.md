# workspace — 统一入口（唯一代码根声明）

> 本目录是本次「逻辑收敛」新增的入口。**不移动、不重命名、不删除任何既有文件**，
> 只通过新增文件与只读软链把散落的代码与产物在逻辑上收敛到唯一根。

## R 是唯一代码根

`R = /Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13`

主仓库 R 是本工作区**唯一的代码根**：应用、生成器、脚本、SQL、配置、文档与所有新建代码
都以 R 为基准定位。本目录 `R/workspace/` 只放「入口与说明」，不放业务代码。

## 三个来源及其角色

| 来源 | 路径 | 角色 |
| --- | --- | --- |
| R 主仓库 | `/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13` | 唯一代码根；应用与生成器所在 |
| W 会话工作区 | `/Users/deocheng/WorkBuddy/2026-07-13-10-47-43` | 历次会话产生的临时 / 补丁脚本与孤儿 HTML 产物 |
| P 仓外产物 | `/Volumes/12T/NBA/nba_analysis` | 96 份批量历史报告产物（html / svg / png / py 等） |

三者通过**只读软链**在 R 内建立可达入口，不做物理搬运：

- `R/workspace/workbuddy-scripts -> W`
- `R/reports/nba-analysis -> P`

## 为什么不移动它们

物理搬运会破坏既有引用并触及受保护资产，因此只做逻辑收敛：

1. **数据源依赖**：R 内大量脚本以绝对路径读取盘根数据、缓存与数据库导出
   （`nba_pg/`、`*_cache/`、`raw_archive/`、`br_*_cache/` 等），改动位置会使这些引用整体失效；
   连接 PostgreSQL 与启动爬虫也不在本次范围内。
2. **6TB 素材**：盘根 `比赛录像/`、`球星/`、`电视节目/`、`资料/`、`Images/` 等为
   mp4 / mp3 / jpg 大体积素材，既不属代码，也严禁全盘递归遍历
   （外置盘遍历会卡死 / 触发 exit 137）。
3. **第三方项目**：`WeVisOne-VL` 为第三方开源项目，按约定**不改造、不纳入本仓库代码治理**。

此外 `.trash`、`raw_archive`、`*_cache`、`.venv`、`.git` 一律不碰。

## 使用约定

- **所有新代码放 `R/`**：业务代码放既有子目录，入口说明放 `R/workspace/`。
- **报告产物放 `R/reports/`**：`README.md` 定义用途与权威版本判定规则，
  `INDEX.md` 为人类可读清单，`manifest.json` 为结构化清单（文件大小从磁盘实读）。
- **盘根旧路径只读**：`/Volumes/12T/NBA/` 下除 R 以外的既有路径只读，
  不写入、不移动、不删除；确需引用时经 `R/workspace/` 与 `R/reports/` 下的软链访问。
- **孤儿产物只登记不删除**：处理原则见 `R/reports/README.md`。
- **补丁反模式的长期方向是修改生成器**：字符串补丁仅用于一次性历史产物，
  见 `W/patch_reports.py` 与 `W/reskin_pace_white.py` 的顶部说明。

## 工具

```bash
cd R
python workspace/entry.py --list     # 打印来源清单与固定路径
python workspace/entry.py --check    # 校验每个来源是否仍存在（OK / MISSING）
```

`entry.py` 只用标准库，仅对固定绝对路径做 `os.path.exists` 单次检查，
**不递归扫描大目录**。来源明细见 `sources.md`。
