# tactics/ — NBA 战术分析项目（代码层）

> 迁入日期 2026-11-11 · 由 `/Volumes/12T/NBA/action_analysis/` 并入主仓库
> 本文档是**目录映射表与运行契约**，不是战术内容说明。

## 1. 定位：代码 / 数据分离

| 层 | 落点 | 是否入库 | 说明 |
|---|---|---|---|
| 代码层 | `REPO_ROOT/tactics/` | ✅ 是（560 文件） | 458 个 `.py` + shell / md / json / yaml，纳入 git、ruff、42 项质量门禁 |
| 数据层 | `DATA_ROOT/action_analysis/` | ❌ 否 | `action_work` / `bonsai` / `clips` / `reports` 的产物、模型权重、`.venv`、素材（约 43G） |
| 第三方 | `bonsai/llama.cpp`、`node_modules`、`RelateAnything` | ❌ 否 | 独立仓库 / 依赖树，留在原地 |

🔴 **迁移时把数据盘原位置换成同名软链指回 `tactics/`**：老脚本里写死的绝对路径在运行时
依然有效，读写落点没有改变。因此「路径治理」是**换机可移植性 + 门禁合规**，不是搬数据。

## 2. 目录映射

| 目录 | 文件数 | `.py` | 职责 |
|---|---:|---:|---|
| `engine/` | 367 | 365 | 主分析引擎：检测、跟踪、关系层、语料/路由、报告生成 |
| `reports/` | 57 | 0 | 里程碑报告与方案（md / json / html），随代码入库供追溯 |
| `clips/` | 48 | 41 | 片段挑选、OCR、候选扫描、签核脚本 |
| `action_work/` | 46 | 31 | 语料构建、标注、A/B 实验、模型加载测试 |
| `vlx_seek/` | 15 | 7 | VLX-Seek 推理封装（第三方大文件留数据盘） |
| `bonsai/` | 14 | 12 | 剪辑 / 融合校准 / 批量签核 |
| `tools/` | 5 | 2 | 战术区自用小工具 |
| `vocab/` | 4 | 0 | 战术术语表与映射 |
| 根 | 4 | 0 | `setup_env*.sh`、`run_validate3.sh` |

## 3. 路径常量（唯一来源）

Python 侧 `common/nba_paths.py`、Shell 侧 `common/paths.sh`，两侧由
`tests/test_path_resolution_parity.py` 锁定 5 项取值一致。

| 常量 | helper | 含义 |
|---|---|---|
| `REPO_ROOT` | `repo_file()` | 主仓库根（R） |
| `DATA_ROOT` | `data_file()` | 数据盘根（D），录像 / 笔记 / 归档 |
| `WORKSPACE_ROOT` | `workspace_file()` | WorkBuddy 会话工作区（W） |
| `TACTICS_CODE_ROOT` | `tactics_code_file()` | `REPO_ROOT/tactics`（代码） |
| `TACTICS_DATA_ROOT` | `tactics_data_file()` | `DATA_ROOT/action_analysis`（数据） |

`docs` / 注释里的绝对根写作占位符 `<DATA_ROOT>` / `<TACTICS_DATA_ROOT>` /
`<WORKSPACE_ROOT>` / `~`，**源码中不得出现绝对路径字面量**（门禁 11a 全文扫描）。

### 运行时自举

`tools/fix_tactics_paths.py` 为用到 helper 的脚本注入幂等 bootstrap：

```python
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path
_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[N]))
from common.nba_paths import data_file, tactics_data_file
```

`sys.path.insert` **必须**先于 `common.nba_paths` 的 import —— 脚本常从任意 cwd
或数据盘软链启动，否则 `common` 找不到。该顺序由
`tests/test_tactics_governance.py::test_bootstrap_single_and_ordered` 锁死。

## 4. 🔴 探测禁令（血泪教训）

**禁止用 `import` 对 `tactics/` 做可导入性冒烟**。约 17% 的脚本没有
`__main__` 守卫，import 即执行；2026-11-11 一次抽样冒烟重跑了语料 / 路由流水线，
**42 个数据产物被重写**。正确做法是 AST 静态解析（`ast.parse`），
回归测试即按此实现。

同样禁止用行级正则批量改写这些脚本：早期版本因此把 import 注进 docstring、
重复注入、替换中文标点、留下未闭合三引号，**458 个 `.py` 中 443 个变得无法解析**
（备份是 458/458 可解析）。当前治理器改为 tokenize / AST 感知，并强制
「改后逐文件语法 + 路径语义等价双校验，失败即整文件丢弃」。

## 5. 治理状态（2026-11-11 实测）

| 项 | 结果 |
|---|---|
| `.py` 语法可解析 | **458 / 458** |
| `.py` 全文硬编码绝对路径 | **0** |
| 路径表达式语义等价 | **454 处逐条求值比对全等** |
| ruff 全仓 | **0 违规** |
| 42 项质量门禁 | **42 / 42** |
| 治理回归测试 | **7 / 7 passed** |
| 迁移完整性（备份 vs 现库） | **560 文件相对路径集合完全一致** |

## 6. 未结项 / 失败边界

1. **12/13 个 `.sh` 仍含硬编码绝对路径**（多为 `cd <数据根>/action_analysis`）。
   门禁 11c 只扫主仓根与 `external_crawler/` 的 `.sh`，当前**不覆盖** `tactics/`；
   且这些脚本依赖数据盘软链，改写收益低于破坏运行的风险 → 保持原状，另行立项。
2. **`__main__` 守卫未强制补齐**：补守卫会改变「import 即执行」的既有语义，
   属独立议题；以探测禁令 + 回归测试先兜住风险。
3. **备份与回滚**：`.trash/tactics_pre_migration_20261111/` 是迁移前原件（md5 全一致）；
   `.trash/tactics_broken_snapshot_20261111_2210/` 是事故现场，
   `.trash/tactics_pre_rufffix_20261111/` 是 ruff 自动修复前快照。三者均在 `.gitignore` 内。
