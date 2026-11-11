#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tactical_annotate.py — 战术解读视频标注管线(A4.55, 老程裁定方案)。

定位(老程 2026-09-29 裁定):
  战术语义来自老程的「带时间戳文字稿」(时刻+战术目的), 工具不自主猜战术。
  交付 = 在视频里逐动作段标注「动作标签 + 战术目的说明」。
  动作段由跟踪层(A4.53 teamID QUALIFIED + A4.54 球轨迹 93%)自动提取:
    PASS = 稳定持球者段 A→B 跨越球飞行间隙(换手); DRIVE = 持球者连续高速;
    球飞行 = 球腾空段(传球/出手)。老程稿里的「动作:」可覆盖自动动作。

铁律:
  - 战术目的 ONLY 来自老程稿; 稿里没有的帧不编目的(只标自动动作或无标注)。
  - 数字全从 A4.54 JSON / 稳定轨迹现读; 不插值; 球标记复用 A4.54(green=detect/orange=inferred)。
  - 源视频由 400 帧 jpg 经 ffmpeg 重建(无原始 mp4); 叠加横幅后编码 mp4。
  - 战术库(A4.56)只作**参考**, 且**仅当稿里显式写了「战术:」字段**才挂库(老程 2026-09-29 裁定):
    在侧车 JSON 附 library_refs(来源期数+人声讲解原文), 并在视频顶栏右侧叠「[库]第N期 战术名」提示。
    库不生成目的、不改稿、不替老程裁定; 没写「战术:」就不提示。
  - 🔴 战术标注的前提 = 片段**确含某个战术**(老程裁定)。即兴配合/单打/失误回合**不得贴战术标签**;
    库匹配命中的是稿里的词, **绝不证明片段含该战术**。非战术回合请如实标注, 不挂库。

用法:
  tactical_annotate.py --clip sas_det --script validate/sas_det_tactical_script.example.md
  tactical_annotate.py --clip sas_det --script <老程稿.md> --out validate/sas_det_tactical_annotated.mp4
  tactical_annotate.py --clip sas_det --script <稿>.md --no-library-hint   # 关闭库提示叠加
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))

TH, DIAG_MAX = 0.30, 60
POSS_RADIUS = 0.04
FPS = 10.0
N = 400
DRIVE_PX_S = 130.0      # 与 tactical_events 同口径
DRIVE_MIN_M = 3
DIAG = math.hypot(1920, 1080)
EXCL_SAS_DET = {31, 33, 38, 44, 64}
EXCL_SAS_LAL = {7, 8, 38}
ADJ_REF = {"sas_det": EXCL_SAS_DET, "sas_lal": EXCL_SAS_LAL}

# ---------------- 战术库(A4.56) ----------------
try:
    from tactic_library import TacticLibrary
except Exception:  # 库模块缺失时不致命
    TacticLibrary = None


def load_library():
    if TacticLibrary is None:
        return None
    try:
        lib = TacticLibrary()
        print(f"[lib] 战术库 {len(lib.topics())} 条已加载")
        return lib
    except Exception as e:
        print(f"[lib] 不可用: {e}")
        return None


def match_tactics(text, lib, max_hits=3):
    """在文本里扫库中战术名/别名(长度>=2, 长名优先)。仅作参考匹配, 不生成内容。"""
    if not lib or not text:
        return []
    t = text.lower()
    pairs = [(a, k) for a, k in lib._alias2key.items() if len(a) >= 2]
    pairs.sort(key=lambda x: -len(x[0]))
    hits, seen = [], set()
    for alias, key in pairs:
        if alias in t and key not in seen:
            seen.add(key)
            hits.append(key)
            if len(hits) >= max_hits:
                break
    return hits


def lib_ref(entry, lib):
    """为一条稿条目求库引用: **仅当显式写了「战术:」字段**才挂库(老程 2026-09-29 裁定)。
    取消「扫『战术目的』文本自动匹配」——那会把描述性文字误当战术点名, 制造假权威。"""
    if not lib or not entry.get("tactic"):
        return []
    cands = []
    v = lib.lookup(entry["tactic"])
    if v:
        cands.append((entry["tactic"], v))
    else:
        for k in match_tactics(entry["tactic"], lib):
            v2 = lib.lookup(k)
            if v2:
                cands.append((k, v2))
    out, seen = [], set()
    for k, v in cands:
        if k in seen:
            continue
        seen.add(k)
        out.append({"tactic": k, "source_clips": v.get("source_clips", []),
                    "timestamps": v.get("timestamps", []),
                    "teaching_excerpt": (v.get("teaching", "") or "")[:200]})
    return out


def ctr(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


# ---------------- 加载 ----------------
def load(clip):
    EXCL = ADJ_REF.get(clip, set())
    a454 = json.loads((AW / "validate" / f"{clip}_ball_track_occluded.json").read_text())
    fr = a454["frame"]
    old = json.loads((AW / f"{clip}_poss_tile_stab" / "ball_tracks.json").read_text())
    states = {r["fid"]: r for r in json.loads((AW / "validate" / f"{clip}_frame_states.json").read_text())["rows"]}
    FR = AW / clip
    tid_bbox = [{} for _ in range(N)]
    for i, f in enumerate(old[:N]):
        for pl in f.get("players", []):
            if pl.get("bbox") and pl.get("track_id") not in EXCL:
                tid_bbox[i][pl["track_id"]] = pl["bbox"]
    return fr, tid_bbox, states, FR, EXCL


# ---------------- 自动动作段 ----------------
def build_segments(fr, tid_bbox, EXCL):
    # 逐帧持球者(球在框内 or 最近球员, 限半径) — 覆盖 detect+attached 两源
    holder = [None] * N
    for i in range(N):
        if fr[i]["ball"] is None:
            continue
        bx, by = fr[i]["ball"]
        best = (1e18, None)
        for tid, b in tid_bbox[i].items():
            if tid in EXCL:
                continue
            if b[0] <= bx <= b[2] and b[1] <= by <= b[3]:
                best = (0, tid); break
            d = math.hypot(ctr(b)[0] - bx, ctr(b)[1] - by)
            if d < best[0]:
                best = (d, tid)
        if best[1] is not None and best[0] <= 0.08 * DIAG:
            holder[i] = best[1]
    # 持球者连续段(HOLD)
    runs = []
    cur = None
    for i in range(N):
        h = holder[i]
        if h is not None and fr[i]["state"] == "HOLD":
            if cur is None:
                cur = (h, i, i)
            elif cur[0] != h:
                runs.append(cur); cur = (h, i, i)
            else:
                cur = (cur[0], cur[1], i)
        else:
            if cur is not None:
                runs.append(cur); cur = None
    if cur is not None:
        runs.append(cur)
    segs = []
    # PASS: 相邻段 tid 不同且间隙<=8帧(非死球重置)
    for k in range(len(runs) - 1):
        a, b = runs[k], runs[k + 1]
        if a[0] != b[0] and (b[1] - a[2]) <= 8:
            segs.append({"type": "PASS", "from": a[0], "to": b[0],
                         "f0": a[2], "f1": b[1], "label": f"PASS tid{a[0]}→tid{b[0]}"})
    # DRIVE: 段内持球者速度>阈值连续>=3帧(速度从稳定轨迹 bbox 中心估)
    tid_spd = {}
    for i in range(1, N):
        for tid in set([holder[i], holder[i - 1]]):
            if tid is None:
                continue
            if tid not in tid_bbox[i] or tid not in tid_bbox[i - 1]:
                continue
            d = math.hypot(ctr(tid_bbox[i][tid])[0] - ctr(tid_bbox[i - 1][tid])[0],
                           ctr(tid_bbox[i][tid])[1] - ctr(tid_bbox[i - 1][tid])[1])
            tid_spd.setdefault(tid, [None] * N)[i] = d * FPS
    for r in runs:
        tid = r[0]
        sp = tid_spd.get(tid, [None] * N)
        run = []
        for i in range(r[1], r[2] + 1):
            if sp[i] is not None and sp[i] > DRIVE_PX_S:
                run.append(i)
            else:
                if len(run) >= DRIVE_MIN_M:
                    segs.append({"type": "DRIVE", "tid": tid, "f0": run[0], "f1": run[-1],
                                 "label": f"DRIVE tid{tid}"})
                run = []
        if len(run) >= DRIVE_MIN_M:
            segs.append({"type": "DRIVE", "tid": tid, "f0": run[0], "f1": run[-1],
                         "label": f"DRIVE tid{tid}"})
    # 球飞行段(state==FLY)
    run = []
    for i in range(N):
        if fr[i]["state"] == "FLY":
            run.append(i)
        else:
            if run:
                segs.append({"type": "FLY", "f0": run[0], "f1": run[-1], "label": "球飞行(传球/出手)"})
                run = []
    if run:
        segs.append({"type": "FLY", "f0": run[0], "f1": run[-1], "label": "球飞行(传球/出手)"})
    segs.sort(key=lambda s: s["f0"])
    return segs, holder


def seg_at(segs, frame):
    for s in segs:
        if s["f0"] <= frame <= s["f1"]:
            return s
    return None


# ---------------- 解析老程稿 ----------------
def parse_script(path):
    txt = Path(path).read_text(encoding="utf-8")
    entries = []
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        # 只认行首的时间标记(可带 - / • 前缀); 支持区间 t=10.1-15.0 或 f=101-150
        mt = re.match(r"^[-•*]?\s*t=([\d.]+)(?:\s*[-~]\s*([\d.]+))?", line)
        mf = re.match(r"^[-•*]?\s*f=(\d+)(?:\s*[-~]\s*(\d+))?", line)
        rng = None
        if mt:
            frame = int(float(mt.group(1)) * FPS)
            if mt.group(2):
                rng = [frame, int(float(mt.group(2)) * FPS)]
        elif mf:
            frame = int(mf.group(1))
            if mf.group(2):
                rng = [frame, int(mf.group(2))]
        else:
            continue
        act_m = re.search(r"动作[:：]\s*([^\n战术]+)", line)
        action = act_m.group(1).strip() if act_m else None
        tac_m = re.search(r"战术(?!目的)[:：]\s*([^战\n]+)", line)
        tactic = tac_m.group(1).strip() if tac_m else None
        pur_m = re.search(r"战术目的[:：]\s*(.*)", line)
        purpose = pur_m.group(1).strip() if pur_m else line
        e = {"frame": frame, "action": action, "tactic": tactic, "purpose": purpose}
        if rng:
            e["range"] = rng
        entries.append(e)
    return entries


# ---------------- 渲染 ----------------
def wrap(text, max_chars):
    out, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= max_chars:
            out.append(cur); cur = ""
    if cur:
        out.append(cur)
    return out


def _ep(src):
    m = re.search(r"第(\d+)期", src or "")
    return f"第{m.group(1)}期" if m else None


def library_hint(e):
    refs = e.get("library_refs") or []
    if not refs:
        return None
    r = refs[0]
    ep = _ep(r["source_clips"][0]) if r.get("source_clips") else None
    tag = ep or (r.get("source_clips") or ["?"])[0][:16]
    return f"[库] {tag} {r['tactic']}"


def render(clip, fr, segs, entries, FR, out_mp4, hint_on=True):
    tmp = AW / "validate" / "_annot_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    # 每帧标注窗口: 稿条目 -> 覆盖其所在动作段(找不到则 ±12 帧)
    ann = {}  # frame -> (action_label, purpose, library_hint)
    for e in entries:
        if e.get("range"):
            f0, f1 = e["range"]
            label = e["action"] if e["action"] else "标注"
        else:
            s = seg_at(segs, e["frame"])
            f0 = s["f0"] if s else max(0, e["frame"] - 2)
            f1 = s["f1"] if s else min(N - 1, e["frame"] + 12)
            label = e["action"] if e["action"] else (s["label"] if s else "动作(跟踪)")
        f0 = max(0, min(N - 1, f0))
        f1 = max(0, min(N - 1, f1))
        hint = library_hint(e) if hint_on else None
        for f in range(f0, f1 + 1):
            ann[f] = (label, e["purpose"], hint)
    W, H = 1280, 720
    sx, sy = W / 1920, H / 1080
    max_chars = int((W - 60) / (0.7 * 22))
    for i in range(N):
        img = cv2.imread(str(FR / f"f{i+1:05d}.jpg"))
        if img is None:
            continue
        img = cv2.resize(img, (W, H))
        # 球标记
        b = fr[i]["ball"]
        if b:
            col = (0, 200, 0) if fr[i]["source"] == "detect" else (0, 165, 255)
            cv2.circle(img, (int(b[0] * sx), int(b[1] * sy)), 9, col, 3)
        if i in ann:
            label, purpose, hint = ann[i]
            # 顶部动作横幅
            cv2.rectangle(img, (0, 0), (W, 52), (0, 80, 0), -1)
            cv2.putText(img, f"动作: {label}", (16, 36), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (255, 255, 255), 2)
            # 顶栏右侧: 战术库参考提示(不虚构, 仅当匹配到)
            if hint:
                (tw, _), _ = cv2.getTextSize(hint, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
                cv2.putText(img, hint, (W - tw - 16, 34), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (150, 255, 150), 1)
            # 底部战术目的横幅(可换行)
            lines = wrap("战术目的: " + purpose, max_chars)
            bh = 30 + 26 * len(lines)
            cv2.rectangle(img, (0, H - bh), (W, H), (30, 30, 0), -1)
            for k, ln in enumerate(lines):
                cv2.putText(img, ln, (16, H - bh + 26 + k * 26), cv2.FONT_HERSHEY_SIMPLEX,
                            0.62, (0, 255, 255), 2)
        cv2.imwrite(str(tmp / f"f{i+1:05d}.png"), img)
    # ffmpeg 编码
    cmd = ["/opt/homebrew/bin/ffmpeg", "-y", "-framerate", str(FPS),
           "-i", str(tmp / "f%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "23", str(out_mp4)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"[ffmpeg] {'OK' if Path(out_mp4).exists() else 'FAIL'} -> {out_mp4}")
    if r.returncode != 0:
        print(r.stderr[-500:])
    shutil.rmtree(tmp, ignore_errors=True)
    return ann


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_det")
    ap.add_argument("--script", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-library-hint", action="store_true", help="不叠加战术库参考提示")
    a = ap.parse_args()
    CLIP = a.clip
    if a.out is None:
        a.out = str(AW / "validate" / f"{CLIP}_tactical_annotated.mp4")
    lib = load_library()
    fr, tid_bbox, states, FR, EXCL = load(CLIP)
    segs, holder = build_segments(fr, tid_bbox, EXCL)
    entries = parse_script(a.script)
    # 为每条稿条目附战术库参考(仅参考, 不改稿)
    n_ref = 0
    for e in entries:
        e["library_refs"] = lib_ref(e, lib)
        if e["library_refs"]:
            n_ref += 1
    print(f"[seg] 自动动作段 {len(segs)} (PASS={sum(1 for s in segs if s['type']=='PASS')} "
          f"DRIVE={sum(1 for s in segs if s['type']=='DRIVE')} FLY={sum(1 for s in segs if s['type']=='FLY')})")
    print(f"[script] 老程稿条目 {len(entries)} (战术目的 ONLY 来自稿, 不伪造)")
    print(f"[lib] 稿条目命中战术库参考 {n_ref}/{len(entries)}")
    # 侧车 JSON(程序可读)
    sidecar = {"clip": CLIP, "auto_segments": segs, "script_entries": entries,
               "library": "tactic_library.json(A4.56)" if lib else None}
    Path(str(AW / "validate" / f"{CLIP}_tactical_annotations.json")).write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=1))
    ann = render(CLIP, fr, segs, entries, FR, a.out, hint_on=not a.no_library_hint)
    matched = sum(1 for e in entries if seg_at(segs, e["frame"]))
    print(f"[align] 稿条目命中自动动作段 {matched}/{len(entries)}; 其余按 ±12 帧窗口标注")
    print(f"[out] 视频 {a.out} | 侧车 {CLIP}_tactical_annotations.json")


if __name__ == "__main__":
    main()
