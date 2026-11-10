#!/usr/bin/env python3
"""把 7 份 analysis_*.html 里内联的 plotly.js bundle 剥离为共享本地 JS 引用。

幂等：已剥离的文件跳过；执行前把原始文件备份到 reports/_pre_strip_backup/。
只替换体积 >1MB 的那段内联 <script>（plotly bundle），保留后面
Plotly.newPlot(...) 所在的 script 段以及其它全部内容。

用法：python3 tools/strip_inline_plotly.py
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [
    "analysis_duo_density.html",
    "analysis_duos_trios.html",
    "analysis_longterm_scatter.html",
    "analysis_player_coaches.html",
    "analysis_salary_share.html",
    "analysis_trio_density.html",
    "analysis_trio_scatter.html",
]
VENDOR_REL = "frontend/vendor/plotly.min.js"
BACKUP_DIR = os.path.join(ROOT, "reports", "_pre_strip_backup")
REPLACEMENT = b'<script src="' + VENDOR_REL.encode() + b'"></script>'
BUNDLE_MIN = 1_000_000
SHRINK_REQUIRED = 0.80  # 每份文件体积需下降 >80%

SCRIPT_RE = re.compile(rb"(<script\b[^>]*>)(.*?)(</script>)", re.S | re.I)


def big_inline_scripts(data):
    """返回所有内联(无 src)且内容 >1MB 的 script 的 match 列表。"""
    out = []
    for m in SCRIPT_RE.finditer(data):
        tag = m.group(1)
        inner = m.group(2)
        if b"src=" in tag.lower():
            continue
        if len(inner) > BUNDLE_MIN:
            out.append(m)
    return out


def main():
    vendor_abs = os.path.join(ROOT, VENDOR_REL)
    if not os.path.isfile(vendor_abs) or os.path.getsize(vendor_abs) < 102400:
        print("ABORT: 本地 vendor 不存在或过小，拒绝剥离（否则会产出打不开的 HTML）:", vendor_abs)
        return 1
    print("vendor 校验通过:", vendor_abs, os.path.getsize(vendor_abs), "bytes")

    # ---- 1) 先完整备份，全部成功后才编辑 ----
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for fn in FILES:
        src = os.path.join(ROOT, fn)
        dst = os.path.join(BACKUP_DIR, fn)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
            # 仅对"本次新建"的备份做字节一致性校验。重跑时备份保留的是
            # 剥离前的原始文件，其大小本来就大于已剥离的当前文件。
            if os.path.getsize(dst) != os.path.getsize(src):
                print("ABORT: 新建备份大小不一致:", fn)
                return 1
        elif os.path.getsize(dst) == 0:
            print("ABORT: 已有备份为空:", fn)
            return 1
    print("备份完成（不覆盖已有备份）:", BACKUP_DIR)

    print()
    header = f"{'文件':<38}{'前(bytes)':>14}{'后(bytes)':>14}{'降幅':>10}  状态"
    print(header)
    print("-" * 84)

    total_before = total_after = 0
    errors = []
    for fn in FILES:
        path = os.path.join(ROOT, fn)
        backup = os.path.join(BACKUP_DIR, fn)
        before = os.path.getsize(path)
        with open(path, "rb") as f:
            data = f.read()

        big = big_inline_scripts(data)
        if not big:
            # 幂等：已剥离过
            if VENDOR_REL.encode() in data and b"Plotly.newPlot" in data:
                after = len(data)
                total_before += before
                total_after += after
                print(f"{fn:<38}{before:>14,}{after:>14,}{'—':>10}  已剥离，跳过")
                continue
            msg = f"{fn}: 未找到 >1MB 内联 script，且未处于已剥离状态"
            errors.append(msg)
            print(f"{fn:<38}{before:>14,}{'-':>14}{'-':>10}  ERROR")
            continue
        if len(big) != 1:
            msg = f"{fn}: 期望 1 个 bundle，实得 {len(big)}"
            errors.append(msg)
            print(f"{fn:<38}{before:>14,}{'-':>14}{'-':>10}  ERROR")
            continue

        m = big[0]
        new_data = data[:m.start()] + REPLACEMENT + data[m.end():]

        # ---- 2) 校验，不通过则回滚该文件 ----
        checks = {
            "含 Plotly.newPlot": b"Plotly.newPlot" in new_data,
            "含 vendor 路径": VENDOR_REL.encode() in new_data,
            "无 >1MB 内联 script": not big_inline_scripts(new_data),
            "体积下降 >80%": len(new_data) < before * (1 - SHRINK_REQUIRED),
        }
        if not all(checks.values()):
            shutil.copy2(backup, path)
            failed = [k for k, v in checks.items() if not v]
            errors.append(f"{fn}: 校验失败 {failed}，已从备份回滚")
            print(f"{fn:<38}{before:>14,}{'-':>14}{'-':>10}  ERROR 已回滚")
            continue

        with open(path, "wb") as f:
            f.write(new_data)
        after = os.path.getsize(path)
        pct = (before - after) / before * 100
        total_before += before
        total_after += after
        print(f"{fn:<38}{before:>14,}{after:>14,}{pct:>9.2f}%  OK")

    print("-" * 84)
    total_pct = (total_before - total_after) / total_before * 100 if total_before else 0
    print(f"{'合计':<38}{total_before:>14,}{total_after:>14,}{total_pct:>9.2f}%")
    print()
    if errors:
        print("存在失败项：")
        for e in errors:
            print("  -", e)
        return 1
    print("全部 7 份剥离完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
