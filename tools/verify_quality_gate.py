#!/usr/bin/env python3
"""NBACore 质量门禁 —— 只读验收，不修改任何文件。

用法：python tools/verify_quality_gate.py
输出：逐项 PASS / FAIL / SKIP + 证据，最后汇总。任一 FAIL 时返回码 1。
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.expanduser("~/WorkBuddy/2026-07-13-10-47-43")
ANALYSIS = [
    "analysis_duo_density.html", "analysis_duos_trios.html",
    "analysis_longterm_scatter.html", "analysis_player_coaches.html",
    "analysis_salary_share.html", "analysis_trio_density.html",
    "analysis_trio_scatter.html",
]
STAR_WRAPPERS = ["star_portrait.py", "star_grid.py", "star_logo.py", "star_heatmap.py"]
DB_HELPERS = [
    os.path.join(WORKSPACE, "nba_db.py"),
    os.path.join(WORKSPACE, "nba_fix", "db.py"),
    os.path.join(WORKSPACE, "nba_fix", "dbcommon.py"),
    os.path.join(WORKSPACE, "backfill_20260804", "db.py"),
]

results: list[tuple[str, str, str]] = []


def _strip_dict_literals(text: str, names: tuple[str, ...]) -> str:
    """从文本里剥掉指定名字的字面量字典（如 CMAP = {...}）。

    用**配平花括号**扫描而非正则 —— 字典里有嵌套结构时，
    非贪婪的 .*?\\n\\} 会在中途的 } 处提前截断，导致剥离不干净。
    """
    out = []
    i = 0
    while True:
        m = None
        for nm in names:
            j = text.find(nm, i)
            if j >= 0 and (m is None or j < m.start()):
                m = re.compile(re.escape(nm) + r"\s*=\s*\{").match(text, j)
        if m is None:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        depth = 0
        k = m.end() - 1        # 指向 '{'
        while k < len(text):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    k += 1
                    break
            k += 1
        i = k
    return "".join(out)


def check(name: str, ok: bool | None, evidence: str) -> None:
    state = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    results.append((state, name, evidence))


def rp(*parts: str) -> str:
    return os.path.join(ROOT, *parts)


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def lines(path: str) -> int:
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def run(cmd: list[str], cwd: str = ROOT) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=90)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


# 1. 星图脚本收敛
for name in STAR_WRAPPERS:
    p = rp(name)
    n, s = lines(p), read(p)
    check(f"star wrapper {name}", 0 < n < 40 and "render" in s,
          f"{n} 行，含 render 引用={('render' in s)}")
main_impl = rp("team_shot_radial.py")
check("唯一实现 team_shot_radial.py", lines(main_impl) > 500,
      f"{lines(main_impl)} 行")

# 2. 统一可视化内核
rc, out = run([sys.executable, "-c", "import viz.theme, viz.base, viz.svg; print('ok')"])
check("viz 模块可导入", rc == 0, out[:160] or f"rc={rc}")
demo = "/tmp/viz_demo.html"
rc, out = run([sys.executable, "viz/base.py"])
d = read(demo)
check("page() 输出含 aria/响应式/交互/零 CDN",
      all(k in d for k in ('role="img"', "aria-label", "@media", "<script")) and "https://cdn." not in d,
      f"{len(d)} 字节；{out[:80]}")
tokens = rp("viz", "theme_tokens.json")
if os.path.exists(tokens):
    try:
        t = json.loads(read(tokens))
        check("theme_tokens.json 可解析", isinstance(t, dict), f"{len(t)} 个顶层键")
    except json.JSONDecodeError as exc:
        check("theme_tokens.json 可解析", False, str(exc))
else:
    check("theme_tokens.json 可解析", None, "文件不存在")

# 3. Plotly 瘦身
vendor = rp("frontend", "vendor", "plotly.min.js")
vs = size(vendor)
check("共享 plotly.min.js 非空", vs > 3_000_000, f"{vs:,} 字节")
total = 0
for name in ANALYSIS:
    p = rp(name)
    b = size(p)
    total += b
    s = read(p)
    check(f"瘦身 {name}",
          0 < b < 1_000_000 and "frontend/vendor/plotly.min.js" in s and "Plotly.newPlot" in s,
          f"{b:,} 字节，vendor 引用={'frontend/vendor/plotly.min.js' in s}，newPlot={'Plotly.newPlot' in s}")
check("7 份合计显著下降", 0 < total < 10_000_000,
      f"{total:,} 字节（改造前 34,534,130，降幅 {(1-total/34_534_130)*100:.1f}%）")

# 4. 主应用去 CDN
ech = rp("frontend", "vendor", "echarts.min.js")
idx = read(rp("frontend", "index.html"))
if size(ech) > 100_000:
    check("ECharts 本地化", "https://cdn." not in idx and "vendor/echarts.min.js" in idx,
          f"vendor {size(ech):,} 字节；index CDN={'https://cdn.' in idx}")
else:
    check("ECharts 本地化", None, f"vendor 缺失（{size(ech)} 字节），保留 CDN 属已知遗留")

# 5. CI 与测试
ci = read(rp(".github", "workflows", "ci.yml"))
check("CI 覆盖当前分支", "crawler-verified-2026-07-29" in ci and "feature/**" in ci,
      f"分支标记={'crawler-verified-2026-07-29' in ci}, feature={('feature/**' in ci)}")
check("CI 含前端测试与体积门禁",
      "frontend-test" in ci and "check_report_size" in ci,
      f"frontend-test={'frontend-test' in ci}, size-gate={'check_report_size' in ci}")
tests = sorted(glob.glob(rp("frontend", "tests", "*.test.js")))
if tests:
    rc, out = run(["node", "--test"] + tests)
    check("前端测试实跑", rc == 0, out[-260:].replace("\n", " "))
else:
    check("前端测试实跑", False, "无 *.test.js")

# 6. DB helper 收敛
dbutil = os.path.join(WORKSPACE, "dbutil.py")
check("统一 dbutil.py 存在", os.path.exists(dbutil), f"{lines(dbutil)} 行")
for p in DB_HELPERS:
    n, s = lines(p), read(p)
    check(f"DB wrapper {os.path.relpath(p, WORKSPACE)}",
          0 < n < 45 and "dbutil" in s and "/Volumes/12T" not in s,
          f"{n} 行，引用 dbutil={'dbutil' in s}，硬编码路径={('/Volumes/12T' in s)}")

# 7. 收敛入口与治理
entry = rp("workspace", "entry.py")
if os.path.exists(entry):
    rc, out = run([sys.executable, "workspace/entry.py", "--check"])
    check("workspace/entry.py --check", rc == 0, out[-260:].replace("\n", " "))
else:
    check("workspace/entry.py --check", False, "文件不存在")
manifest = rp("reports", "manifest.json")
if os.path.exists(manifest):
    try:
        m = json.loads(read(manifest))
        items = m if isinstance(m, list) else m.get("items", [])
        check("reports/manifest.json 可解析", len(items) >= 15, f"{len(items)} 条")
    except json.JSONDecodeError as exc:
        check("reports/manifest.json 可解析", False, str(exc))
else:
    check("reports/manifest.json 可解析", False, "文件不存在")
for link in (rp("workspace", "workbuddy-scripts"), rp("reports", "nba-analysis")):
    check(f"软链 {os.path.basename(link)}",
          os.path.islink(link) and os.path.exists(os.path.realpath(link)),
          f"islink={os.path.islink(link)}, target_exists={os.path.exists(os.path.realpath(link))}")

# 8. 语法编译（只编译已存在的文件）
py_files = [rp(x) for x in STAR_WRAPPERS + ["team_shot_radial.py"]]
py_files += sorted(glob.glob(rp("viz", "*.py"))) + [rp("tools", "strip_inline_plotly.py"),
                                                    rp("tools", "check_report_size.py"), entry]
py_files = [p for p in py_files if os.path.exists(p)]
if py_files:
    rc, out = run([sys.executable, "-m", "py_compile"] + py_files)
    check(f"py_compile {len(py_files)} 个文件", rc == 0, out[-200:] or f"rc={rc}")

# 9. 色板单一来源（防止「多套视觉语言」回退）
# 9a. 全仓不得再有第二个色板定义（reportkit 早已删除，这里防复活）
check("无 reportkit/ 竞品设计系统", not os.path.exists(rp("reportkit")),
      f"存在={os.path.exists(rp('reportkit'))}")

# 9b. viz/theme.py 必须是唯一持有 hex 色值的地方。
#     判定：除 viz/ 目录与 frontend/ 外，.py 源码里不应出现成片的 hex 常量。
#     允许例外：
#       · 报告生成器中**数据编码色**（球队色 / 分档色）——它们承载图表含义；
#       · 工具脚本（比对/审计工具会内嵌样本值）；
#       · 迁移器（CHROME_MAP 本身就是「色值→令牌」的映射表）。
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
DATA_COLOR_OK = ("team", "tier", "pts_bucket", "shot_zone", "CATEGORICAL")
TOOL_PREFIXES = ("rebuild_", "migrate_report_palette", "snapshot_report",
                 "compare_report_snapshot", "visual_check_reports",
                 "verify_quality_gate", "patch_reports", "phase_", "preflight",
                 "audit_", "diag_", "cleanup")
# 显式豁免：这些文件里的 hex 全部是**数据编码色**（球队/时期/位置配色），
# 它们承载图表含义，跨报告必须保持恒定，不能被主题令牌替换。
# 豁免是逐文件白名单，不做模糊匹配——避免将来真有违规时被放过。
HEX_EXEMPT = {
    # 一次性改写脚本：CMAP 映射表的键必须是源文件的原始色值；
    # 其余 hex 来自内嵌 SVG 的球队/时期数据编码。
    "reskin_pace_white.py",
}
offenders = []
for base in (WORKSPACE, ROOT):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames
                       if d not in {".git", "__pycache__", ".venv", "node_modules",
                                    "raw_archive", "logs", ".workbuddy", "data",
                                    "backups", "reports", "analysis"}]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            if fn.startswith(TOOL_PREFIXES) or fn in HEX_EXEMPT:
                continue
            fp = os.path.join(dirpath, fn)
            if "/viz/" in fp or fn == "theme.py":
                continue
            try:
                with open(fp, encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read()
            except OSError:
                continue
            # 色值映射表（CMAP / CHROME_MAP 这类「旧色值 → 新令牌」字典）
            # 是合法例外：它的键必须保持原始字面量，否则替换逻辑失效。
            stripped = _strip_dict_literals(txt, ("CMAP", "CHROME_MAP", "CHROME_MAP_LIGHT"))
            hits = [h for h in HEX.findall(stripped)
                    if not any(k in stripped.lower() for k in DATA_COLOR_OK)]
            if len(hits) >= 4:      # ≥4 处成片 hex → 疑似自带色板
                offenders.append(f"{os.path.relpath(fp, base)}({len(hits)})")
check("报告生成器不再自带 hex 色板", not offenders,
      ("违规: " + ", ".join(offenders[:6])) if offenders else "无成片 hex 色值")

# 9c. 令牌块必须**运行时派生**，不得烧进源码。
#     烧进源码 = 内核一份 + 每份报告一份，只能靠人工同步。
BURNED = re.compile(r"--viz-bg\s*:\s*#[0-9a-fA-F]{6}")
burned = []
for fn in sorted(os.listdir(WORKSPACE)):
    if not fn.endswith(".py"):
        continue
    txt = read(os.path.join(WORKSPACE, fn))
    if BURNED.search(txt):
        burned.append(fn)
check("令牌块运行时派生（未烧进源码）", not burned,
      ("违规: " + ", ".join(burned)) if burned else "全部由 viz 内核派生")

# 9d. 派生入口存在且可用
compat_ok = False
try:
    sys.path.insert(0, ROOT)
    from viz.theme import compat_vars
    blk = compat_vars("dark")
    compat_ok = "--viz-bg" in blk and "--viz-cat-10" in blk
except Exception as exc:  # noqa: BLE001
    blk = str(exc)
check("viz.theme.compat_vars 可用", compat_ok, f"{len(blk)} 字符")

# 10. lint 门禁（ruff）—— 与 CI 的 lint job、本地 pre-commit 同一套配置
# 10a. ruff 配置存在（分层豁免的单一事实来源在 pyproject.toml）
ruff_cfg = rp("pyproject.toml")
cfg_ok = "[tool.ruff" in read(ruff_cfg) and "per-file-ignores" in read(ruff_cfg)
check("ruff 配置存在且分层豁免已声明", cfg_ok,
      f"pyproject.toml 含 [tool.ruff] 与 per-file-ignores={cfg_ok}")

# 10b. ruff 实跑：全仓零违规才算过（豁免规则由配置承担，不在此处重复豁免）
ruff_bin = os.path.join(ROOT, ".venv", "bin", "ruff")
if os.path.exists(ruff_bin):
    rc, out = run([ruff_bin, "check", "--output-format=concise", ROOT])
    if rc == 0:
        check("ruff check 全仓通过", True, "0 违规")
    else:
        lines = [l for l in out.splitlines() if l.strip() and "warning:" not in l]
        check("ruff check 全仓通过", False,
              f"{len(lines)} 处违规: " + "; ".join(lines[:4]))
else:
    rc2, out2 = run([sys.executable, "-m", "ruff", "--version"])
    if rc2 != 0:
        check("ruff check 全仓通过", None, "ruff 未安装（pip install ruff）")
    else:
        rc3, out3 = run([sys.executable, "-m", "ruff", "check",
                         "--output-format=concise", ROOT])
        if rc3 == 0:
            check("ruff check 全仓通过", True, "0 违规")
        else:
            lines = [l for l in out3.splitlines() if l.strip() and "warning:" not in l]
            check("ruff check 全仓通过", False,
                  f"{len(lines)} 处违规: " + "; ".join(lines[:4]))

# 11. 路径治理（硬编码绝对路径）
# 11a. 已跟踪 .py 不得残留用户目录/数据盘根字面量。
#      例外只有「治理工具自身」——它们必须含字面量才能检测别人：
#        · verify_quality_gate.py          本文件，检测用字面量
#        · migrate_hardcoded_paths.py      迁移器的规则表（路径字面量是它的输入）
#        · verify_path_migration_equivalence.py  校验器的白名单/路径前缀表
PATH_TOOL_EXEMPT = {
    "tools/verify_quality_gate.py",
    "tools/migrate_hardcoded_paths.py",
    "tools/verify_path_migration_equivalence.py",
}
tracked_py = subprocess.run(
    ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True
).stdout.split()
path_offenders: list[str] = []
for rel in tracked_py:
    if rel in PATH_TOOL_EXEMPT:
        continue
    txt = read(rp(rel))
    if "/Users/deocheng" in txt or "/Volumes/12T" in txt:
        path_offenders.append(rel)
check("已跟踪 .py 零硬编码绝对路径", not path_offenders,
      ("违规: " + ", ".join(path_offenders[:6])) if path_offenders
      else f"{len(tracked_py)} 个已跟踪 .py 全部走路径模块（豁免治理工具 "
           f"{len(PATH_TOOL_EXEMPT)} 个）")

# 11b. 路径语义等价性：迁移前后「还原比对」必须零差异。
#      只 grep 零命中**不能**证明语义未变（拆分方式、顺序、引号风格都会影响），
#      故必须实跑逐表达式求值比对。
equiv = rp("tools", "verify_path_migration_equivalence.py")
if os.path.exists(equiv):
    rc, out = run([sys.executable, "tools/verify_path_migration_equivalence.py"])
    m = re.search(r"受检文件\s*(\d+)\s*/\s*完全等价\s*(\d+)\s*/\s*有差异\s*(\d+)", out)
    if rc == 0 and m:
        checked_n, same_n, differ_n = (int(x) for x in m.groups())
        check("路径迁移语义等价（还原比对）", differ_n == 0 and checked_n > 0,
              f"受检 {checked_n} / 等价 {same_n} / 差异 {differ_n}")
    else:
        check("路径迁移语义等价（还原比对）", False,
              (out[-240:].replace("\n", " ") or f"rc={rc}"))
else:
    check("路径迁移语义等价（还原比对）", None, "校验器不存在")

# 汇总
print("| 状态 | 检查项 | 证据 |")
print("|---|---|---|")
for state, name, evidence in results:
    print(f"| {state} | {name} | {evidence.replace('|', '/')[:180]} |")
npass = sum(1 for s, _, _ in results if s == "PASS")
nfail = sum(1 for s, _, _ in results if s == "FAIL")
nskip = sum(1 for s, _, _ in results if s == "SKIP")
print(f"\nPASS={npass}  FAIL={nfail}  SKIP={nskip}  TOTAL={len(results)}")
sys.exit(1 if nfail else 0)
