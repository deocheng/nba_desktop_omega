#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""融合判定器：门控6(记分牌 ROI 静态差 = DEAD 软权威) + 本地 Qwen 多帧 LIVE 确认器。

设计依据（均已磁盘实证，非臆测）：
  - 门控6 生产者 shot_scale_seq.py：ROI=1920x1080 原生 x[978,1186] y[943,986]，
    逐采样点 sb = mean(absdiff(roi,prev_roi)) < 12.0；sb=True = 记分牌叠层静止存在。
  - refine_candidates.py 取特写段 sb 均值 = sb_frac，仅标记不自动排除。
  - 🔴 **真实全量 sb 数据（裁剪依据.md 第三部分，上半场重扫含 sb）推翻"sb高=吹停"假设**：
      cand1244=1.00(吹停/EXCLUDE)、cand932=1.00(一次进攻/KEEP)、
      cand1119=1.00(一次进攻/KEEP)、full_poss428=0.75(KEEP)、possA=0.20(活球/KEEP)。
    ⇒ sb_frac=1.0 既含 EXCLUDE 也含 KEEP，**门控6 对 EXCLUDE/KEEP 无区分力**；
      老程亦裁定"记分牌在≠吹停，第6门控从硬排除改仅标记"。
  - 本地 Qwen2.5-VL-3B 多帧实测：cand1244→LIVE 0.99(错判,应EXCLUDE)；
    cand932/possA_full→LIVE 正确。⇒ Qwen 把吹停帧高置信错判 LIVE，DEAD 判定不可信。
  - 结论（诚实）：当前两信号都不可靠区分吹停 vs 活球特写。自动流程只能做到
    **门控6 干净段(sb 低)自动 KEEP + 其余交老程**(recall 工具非 precision 工具)。

判定纯逻辑（fuse_verdict，可独立单测）：
  sb_frac <  0               → HUMAN_REVIEW   (无 sb 数据，无法判定)
  sb_frac <  SB_FRAC_SOFT    → KEEP           (特写无记分牌=进攻镜头语言，possA 实证)
  sb_frac >= SB_FRAC_SOFT    → HUMAN_REVIEW   (高 sb 既可能活球特写也可能吹停，
                                              两信号无区分力，交老程；qwen_live 仅记录参考)

用法：
  fusion_judge.py --cands-json <refine输出.json> --src <clean.mp4> \
                  [--qwen-url http://127.0.0.1:8099/v1/chat/completions] \
                  [--out fusion_verdicts.json] [--no-qwen] [--conf-thr 0.90]

  也可作为管线阶段导入：from fusion_judge import fuse_half
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# ---- 门控6 常量（与 shot_scale_seq.py 严格一致，来源已核实）----
SB_X0, SB_X1 = 978, 1186
SB_Y0, SB_Y1 = 943, 986
SB_THR = 12.0  # 灰度帧差均值阈值：<此值=ROI 静态=记分牌在

# ---- 融合阈值（标定自真实全量 sb 数据 + 老程裁定，见 docstring）----
SB_FRAC_SOFT = 0.50   # <此值：特写无记分牌 → KEEP（进攻镜头语言）；≥此值→交老程
QWEN_LIVE_MIN = 0.90  # Qwen LIVE 置信下限（仅记录参考，不用于自动 EXCLUDE）

QWEN_URL = "http://127.0.0.1:8099/v1/chat/completions"
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
PROMPT = ("这几张图是同一个连续篮球进攻镜头的不同时间点（按时间先后）。"
          "请判断：这个镜头语言展现的是“活球进攻进行中”(LIVE)，"
          "还是“死球/吹停/回放/入场仪式等转场”(DEAD)？"
          "只输出一个词：LIVE 或 DEAD。")


# ---------------------------------------------------------------------------
# 纯逻辑（无 IO，可独立单测）
# ---------------------------------------------------------------------------
def fuse_verdict(sb_frac, qwen_live,
                 sb_soft=SB_FRAC_SOFT, qwen_min=QWEN_LIVE_MIN):
    """返回 (verdict, conf, reason)。verdict ∈ {KEEP, EXCLUDE, HUMAN_REVIEW}。
    依据真实全量 sb 数据：高 sb 对 KEEP/EXCLUDE 无区分力，故 ≥sb_soft 一律交老程；
    Qwen 把吹停帧错判 LIVE，其 qwen_live 仅记录参考，不参与自动裁定。"""
    if sb_frac is None or sb_frac < 0:
        return ("HUMAN_REVIEW", 0.0,
                f"sb_frac={sb_frac}(无数据)→无法自动判定，交老程")
    if sb_frac < sb_soft:
        return ("KEEP", round(1.0 - sb_frac, 2),
                f"sb_frac={sb_frac:.2f}<{sb_soft}→特写无记分牌=进攻镜头语言")
    # 高 sb：两信号都无区分力 → 交老程（记录 qwen_live 供参考）
    qinfo = "" if qwen_live is None else f" (Qwen LIVE={qwen_live:.2f},不可信)"
    return ("HUMAN_REVIEW", 0.0,
            f"sb_frac={sb_frac:.2f}≥{sb_soft}→高 sb 无区分力(活球特写/吹停皆有){qinfo}→交老程")


# ---------------------------------------------------------------------------
# 门控6：从源视频特写段现算 sb_frac（与 shot_scale_seq 同算法，自包含）
# ---------------------------------------------------------------------------
def compute_sb_frac(src, t0, t1, step=1.0, tmp=None):
    """在 [t0,t1] 区间抽帧，逐帧算记分牌 ROI 静态差，返回 sb 均值(-1.0=无帧/退化窗口)。"""
    import cv2
    import numpy as np
    if t1 - t0 <= 0:
        return -1.0
    tmp = tmp or os.path.join(SCRATCH, "sb")
    os.makedirs(tmp, exist_ok=True)
    mp4 = os.path.join(tmp, "seq.mp4")
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {t1 - t0} -an -vf "fps={1.0/step:.6f}" '
                   f'-c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p "{mp4}"',
                   shell=True, capture_output=True)
    cap = cv2.VideoCapture(mp4)
    rois, prev = [], None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        h, w = fr.shape[:2]
        x0 = int(round(SB_X0 / 1920 * w)); x1 = int(round(SB_X1 / 1920 * w)) + 1
        y0 = int(round(SB_Y0 / 1080 * h)); y1 = int(round(SB_Y1 / 1080 * h)) + 1
        roi = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)[y0:y1, x0:x1]
        rois.append(roi)
    cap.release()
    if len(rois) < 2:
        return -1.0
    sbs = []
    for i in range(1, len(rois)):
        sbs.append(1 if float(np.mean(cv2.absdiff(rois[i], rois[i-1]))) < SB_THR else 0)
    return round(float(np.mean(sbs)), 2)


# ---------------------------------------------------------------------------
# 本地 Qwen：多帧喂图 + logprobs 取首词 LIVE/DEAD 真实概率（前缀匹配）
# ---------------------------------------------------------------------------
def extract_frames(src, t0, t1, n=4, w=480, h=270, tmp=None):
    """在 [t0,t1] 均匀抽 n 帧到 tmp/f001..jpg，返回路径列表。"""
    import cv2
    if t1 - t0 <= 0:
        return []  # 退化窗口（close 段零长）→ 无帧，call_qwen_live([]) 返回 None
    tmp = tmp or os.path.join(SCRATCH, "frames")
    os.makedirs(tmp, exist_ok=True)
    for f in glob.glob(os.path.join(tmp, "f*.jpg")):
        os.remove(f)
    # 先抽流再逐帧抽，避开中段跳转损坏
    mp4 = os.path.join(tmp, "seq.mp4")
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {t1 - t0} -an -vf "fps={n/(t1-t0):.6f}" '
                   f'-c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p "{mp4}"',
                   shell=True, capture_output=True)
    cap = cv2.VideoCapture(mp4)
    paths, i = [], 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        p = os.path.join(tmp, f"f{i+1:03d}.jpg")
        cv2.imwrite(p, fr)
        paths.append(p); i += 1
    cap.release()
    return paths


def _parse_live(top_logprobs):
    """首 token 的 top_logprobs 列表（[{token,logprob},...]），前缀匹配聚合 LIVE/DEAD。
    None=无法解析。"""
    import math
    if not isinstance(top_logprobs, list):
        return None
    live = dead = 0.0
    for item in top_logprobs:
        tok = item.get("token", "")
        lp = item.get("logprob", 0.0)
        prob = float(math.exp(lp)) if isinstance(lp, float) else float(lp)
        if tok.startswith("LIVE") or "LIVE".startswith(tok):
            live += prob
        elif tok.startswith("DEAD") or "DEAD".startswith(tok):
            dead += prob
    tot = live + dead
    return round(live / tot, 2) if tot > 0 else None


def call_qwen_live(frames, qwen_url=QWEN_URL, temperature=0.0):
    """多帧喂 Qwen，取首生成 token 的 LIVE/DEAD 聚合概率。None=不可达。
    健壮性：单请求图片数超限会 400，递归减半重试到 1 帧。"""
    import base64
    # 绕过沙箱代理（127.0.0.1 本地 server 不能走代理，否则 502）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if not frames:
        return None
    parts = [{"type": "text", "text": PROMPT}]
    for p in frames:
        b64 = base64.b64encode(open(p, "rb").read()).decode()
        parts.append({"type": "image_url",
                      "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    payload = {
        "model": "local",
        "messages": [{"role": "user", "content": parts}],
        "temperature": temperature,
        "max_tokens": 4,
        "logprobs": True,
        "top_logprobs": 10,
    }
    req = urllib.request.Request(
        qwen_url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=120) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError:
        # 图片数超限等：减半重试
        if len(frames) > 1:
            return call_qwen_live(frames[::2], qwen_url, temperature)
        return None
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return None
    try:
        toks = data["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
    except (KeyError, IndexError, TypeError):
        return None
    return _parse_live(toks)


# ---------------------------------------------------------------------------
# 编排：单候选
# ---------------------------------------------------------------------------
def judge_candidate(c, src, qwen_url=QWEN_URL, use_qwen=True,
                    close_span=None):
    """c = refine 候选 dict（含 close=[t0,t1,hmed]）。返回带 verdict 的新 dict。"""
    # 特写段时间窗（默认用候选 close 段；可外部覆盖）
    if close_span:
        ct0, ct1 = close_span
    else:
        ct0, ct1 = c["close"][0], c["close"][1]
    # 退化 close 段（零长/过短）→ 退回整候选 clip 窗口，避免零长除零且仍能算 sb
    if ct1 - ct0 < 0.5:
        ct0, ct1 = c["clip"][0], c["clip"][1]
    # 优先用 refine 已算的特写段 sb_frac（与裁剪依据 sb 同源、窗口一致，判定可靠）；
    # 仅在缺失/无效时现算（gold-clip 整段验证路径 c 无 sb_frac，须对整段重算）。
    # 🔴 历史 bug：旧版一律现算 close[0:2]（2s 端点窗）导致与 refine 窗口错位、28 候选恒得 0.75、
    #   自动 KEEP 分支(sb<0.5)从不触发。现改优先消费 refine 值。
    sb_frac = c.get("sb_frac")
    if sb_frac is None or sb_frac < 0:
        sb_frac = compute_sb_frac(src, ct0, ct1)
    qwen_live = None
    # 高 sb 档调用 Qwen 仅记录 qwen_live 供老程参考（不自动裁定，因 Qwen 把吹停错判 LIVE）
    if use_qwen and sb_frac is not None and sb_frac >= SB_FRAC_SOFT:
        frames = extract_frames(src, ct0, ct1, n=4)
        qwen_live = call_qwen_live(frames, qwen_url)
    verdict, conf, reason = fuse_verdict(sb_frac, qwen_live)
    out = dict(c)
    out.update({"sb_frac": sb_frac, "qwen_live": qwen_live,
                "verdict": verdict, "conf": conf, "reason": reason})
    return out


# ---------------------------------------------------------------------------
# 管线阶段：批量裁定（run_nbacup_pipeline.py 可直接 import 此函数）
# ---------------------------------------------------------------------------
def fuse_half(cands_json, src, qwen_url=QWEN_URL, use_qwen=True, out=None):
    """读 refine 候选 JSON，逐条融合裁定，写 fusion_verdicts.json + 可读报告。
    返回 (kept, exclude, review) 三类候选列表，供管线决定剪/不剪。"""
    cands = json.load(open(cands_json))["cands"]
    kept, exclude, review = [], [], []
    for c in cands:
        r = judge_candidate(c, src, qwen_url, use_qwen)
        (kept if r["verdict"] == "KEEP"
         else exclude if r["verdict"] == "EXCLUDE"
         else review).append(r)
    if out is None:
        out = os.path.join(os.path.dirname(cands_json), "fusion_verdicts.json")
    json.dump({"kept": kept, "exclude": exclude, "review": review},
              open(out, "w"), ensure_ascii=False, indent=1)
    # 可读报告
    rep = os.path.join(os.path.dirname(cands_json), "fusion_report.md")
    with open(rep, "w") as f:
        f.write("# 融合判定报告\n\n")
        f.write(f"- KEEP(自动剪): {len(kept)}\n- EXCLUDE(不剪): "
                f"{len(exclude)}\n- HUMAN_REVIEW(交老程): {len(review)}\n\n")
        for tag, lst in (("KEEP", kept), ("EXCLUDE", exclude), ("REVIEW", review)):
            for r in lst:
                f.write(f"- [{tag}] far={r['far'][0]} close={r['close'][1]} "
                        f"sb={r['sb_frac']} qwen={r.get('qwen_live')} "
                        f"conf={r['conf']} :: {r['reason']}\n")
    return kept, exclude, review


def main():
    global QWEN_LIVE_MIN
    ap = argparse.ArgumentParser()
    ap.add_argument("--cands-json", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--qwen-url", default=QWEN_URL)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-qwen", action="store_true")
    ap.add_argument("--conf-thr", type=float, default=QWEN_LIVE_MIN)
    a = ap.parse_args()
    QWEN_LIVE_MIN = a.conf_thr
    kept, excl, rev = fuse_half(a.cands_json, a.src, a.qwen_url,
                                use_qwen=not a.no_qwen, out=a.out)
    print(f"KEEP={len(kept)} EXCLUDE={len(excl)} REVIEW={len(rev)}")
    print("wrote fusion_verdicts.json + fusion_report.md")


if __name__ == "__main__":
    main()
