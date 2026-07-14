#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_archive.py —— 归档校验（T05 收尾，P2-2）
==============================================
列举 raw_archive/br/**/*.html 与 raw_archive/espn/**/*.json，
比对：
  - game_id_map(pbp_under_br = true) 行数  vs  BR HTML 文件数（非空）
  - espn_boxscore 行数                   vs  ESPN JSON 文件数（非空）
校验非空 + 可选 .sha256 完整性，输出缺口清单。

设计目标：即便归档文件很少/为空也能跑通不崩，仅输出缺口清单（呼应完成判定 #6）。
支持:
  --sha256   校验 .sha256 伴生文件完整性（默认不校验，仅做非空 + 计数比对）
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common.bridge_constants import get_pg_conn, PROJECT_ROOT  # noqa: E402
import raw_archiver  # noqa: E402

BR_ROOT = os.path.join(PROJECT_ROOT, "raw_archive", "br")
ESPN_ROOT = os.path.join(PROJECT_ROOT, "raw_archive", "espn")


def list_br_html():
    out = []
    if os.path.isdir(BR_ROOT):
        for root, _, files in os.walk(BR_ROOT):
            for f in files:
                if f.endswith(".html"):
                    out.append(os.path.join(root, f))
    return out


def list_espn_json():
    out = []
    if os.path.isdir(ESPN_ROOT):
        for root, _, files in os.walk(ESPN_ROOT):
            for f in files:
                if f.endswith(".json"):
                    out.append(os.path.join(root, f))
    return out


def db_counts(conn):
    """返回 {br_pbp_under, espn_boxscore}；表缺失时返回 None。"""
    counts = {"br_pbp_under": None, "espn_boxscore": None}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM game_id_map WHERE pbp_under_br = true")
            counts["br_pbp_under"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM espn_boxscore")
            counts["espn_boxscore"] = cur.fetchone()[0]
    except Exception as e:  # noqa: BLE001
        print(f"  ! DB 计数失败(表可能未建): {e}", flush=True)
    return counts


def main():
    ap = argparse.ArgumentParser(description="归档校验（文件数 vs 表行数 + 非空 + 可选哈希）")
    ap.add_argument("--sha256", action="store_true", help="校验 .sha256 完整性")
    args = ap.parse_args()

    br_files = list_br_html()
    espn_files = list_espn_json()
    print(f"[i] BR HTML 文件: {len(br_files)}   ESPN JSON 文件: {len(espn_files)}", flush=True)

    # 非空校验
    nonempty_br = [f for f in br_files if os.path.getsize(f) > 0]
    nonempty_espn = [f for f in espn_files if os.path.getsize(f) > 0]
    empty_br = len(br_files) - len(nonempty_br)
    empty_espn = len(espn_files) - len(nonempty_espn)

    # 哈希校验（可选）
    sha_fail = 0
    if args.sha256:
        for f in nonempty_br + nonempty_espn:
            if not raw_archiver.verify_sha256(f):
                sha_fail += 1
                print(f"  ! 哈希不符/缺 .sha256: {os.path.relpath(f, PROJECT_ROOT)}", flush=True)

    # DB 计数（连不上也只做文件层校验，不崩）
    conn = None
    try:
        conn = get_pg_conn()
        dbc = db_counts(conn)
    except Exception as e:  # noqa: BLE001
        print(f"  ! 无法连接 DB（仅做文件层校验）: {e}", flush=True)
        dbc = {"br_pbp_under": None, "espn_boxscore": None}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    print("\n=== 归档校验报告 ===", flush=True)
    print(f"BR  HTML 文件: {len(br_files)} (非空 {len(nonempty_br)}, 空 {empty_br})", flush=True)
    print(f"ESPN JSON 文件: {len(espn_files)} (非空 {len(nonempty_espn)}, 空 {empty_espn})", flush=True)
    print(f"DB  game_id_map.pbp_under_br = {dbc['br_pbp_under']}", flush=True)
    print(f"DB  espn_boxscore 行数        = {dbc['espn_boxscore']}", flush=True)

    # 缺口分析
    gaps = []
    if dbc["br_pbp_under"] is not None and dbc["br_pbp_under"] > len(nonempty_br):
        gaps.append(f"BR: {dbc['br_pbp_under'] - len(nonempty_br)} 场 pbp_under_br=true 但缺 HTML 文件")
    if dbc["espn_boxscore"] is not None and dbc["espn_boxscore"] > len(nonempty_espn):
        gaps.append(f"ESPN: {dbc['espn_boxscore'] - len(nonempty_espn)} 行 espn_boxscore 但缺 JSON 文件")
    if empty_br:
        gaps.append(f"BR: {empty_br} 个空 HTML 文件")
    if empty_espn:
        gaps.append(f"ESPN: {empty_espn} 个空 JSON 文件")
    if args.sha256 and sha_fail:
        gaps.append(f"哈希校验: {sha_fail} 个文件不符或缺 .sha256")

    print("\n缺口清单:", flush=True)
    if gaps:
        for g in gaps:
            print(f"  - {g}", flush=True)
    else:
        print("  (无缺口)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
