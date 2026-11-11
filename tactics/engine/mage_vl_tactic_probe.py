#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mage_vl_tactic_probe.py — 分层融合架构的「理解层」探针骨架
=============================================================

定位（见 reports/milestone_05/valen_lite_to_mage_mainline_20261003.md §7/§8）：
    【检测层 YOLO 系】→ 干净结构化信号（ball_tracks / tracks_cf / detect_primitives / RelateAnything）
    【理解层 Mage-VL】→ 输入 40-50s 干净半场 clip + 本探针生成的「结构化提示」→ 高层战术描述
    【打分层 Valen】  → 远期，本探针不实现

本文件职责（不下载权重也可跑通的部分）：
    1. 从检测层落盘产物构造「YOLO→Mage-VL 提示」（§8 模板），占位符由真实 JSON 填充
    2. 加载 ASR 真值（asr_segment_annotation.json 的 episode_tactics + cues）—— 标签只信 ASR
    3. 双基线 + 信息量对照评估（防假完整铁律）：随机基线 + 多数类基线 + clip vs 单帧信息增益
    4. Mage-VL 推理接口（mage_vl_infer）为 STUB：本地无权重时返回 None 并明确报错，不伪造输出

设计纪律（老程 2026-10-03）：
    - 检测层与理解层分层：本探针不替换 YOLO 检测跟踪，只把其结构化结果喂给理解层
    - 标签只信 ASR：Mage-VL 描述只在 ASR 留出集上评估，模型不当裁判
    - 双基线必报：任何「Mage-VL 描述质量高」结论须由 ASR 留出集 + 双基线支撑
    - 禁假完整：数字全从磁盘现读；无权重时不编造 Mage-VL 文本，只验证 harness 接线

依赖（仅复用既有 engine，不重造）：
    tactic_match_real.load_clip / derive_thresholds
    tactic_match.detect_primitives
"""
import argparse
import json
import re
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AW = ROOT / "action_work"
ENG = ROOT / "engine"
import sys

sys.path.insert(0, str(ENG))

from tactic_match import detect_primitives  # noqa: E402
from tactic_match_real import derive_thresholds, load_clip  # noqa: E402

# Mage-VL 权重默认位置（本地当前无；下载后改此处或传 --mage-weights）
DEFAULT_MAGE_WEIGHTS = AW / "weights" / "Mage-VL"

# Mage-VL 推理运行时参数（老程 2026-10-03 裁定：接 BF16 离线）
# 实测基线（M4 MPS / fp16 / 8帧 / 4170ctx）：prefill 42.98s + decode 2.063s/token
# 帧数直接决定 context 长度与 prefill 耗时（线性），默认 16 帧平衡"捕运动"与"速度"。
# 帧数直接决定上下文与工作集；分辨率决定每帧 patch 数。
# 实测（M4 16GB）：总 patch 是 memory 硬顶的驱动量，安全水位 ≈16320 patch。
# 1280x720 原生 × 16 帧 = 56320 patch ⇒ 换页抖动（swap 打满）；必须靠缩帧换帧数。
# max_pixels 对视频链路实测无效 ⇒ 直接缩 PIL 帧。预算表见 reports/...mage_vl_local_runnability_20261003.md §9。
MAGE_NUM_FRAMES = 24          # 480x270×32 或 512x288×24 均在安全水位内
MAGE_FRAME_SIZE = (512, 288)  # "多而粗"：同总 patch 预算下换取更多帧（要时序而非细节）
MAGE_MAX_TOKENS = 64
# 解码策略（2026-10-04 证伪实验确立）：退化根因是 greedy+提示模板诱导，不是分辨率。
# 实测 ep10_s0：512x288x24 → "[战术描述]"；640x360x16 → "进攻配合战术描述如下："，
# **提分辨率不改善** ⇒ 级联应换成「解码策略级联」，不是「分辨率级联」。
MAGE_DO_SAMPLE = False
MAGE_TEMPERATURE = None
MAGE_REPETITION_PENALTY = None   # 建议 1.1~1.3
MAGE_NO_REPEAT_NGRAM = None      # 建议 3~5
MAGE_SIMPLE_PROMPT = False       # True=用短指令替代 §8 结构化模板（去"1./2."编号诱导）
# 懒加载单例（Mage-VL 权重加载约 176s，批量时必须只加载一次）
_MAGE_MODEL = None
_MAGE_PROCESSOR = None

# 图版/战术讲解纸板段（老程 2026-10-03 裁定：剔除出主战术语料，不进 Mage 理解层主素材）
# 来源：reports/milestone_05/p0_feasibility_recon_20261003.md 视觉自证 + A6 记忆
# 这些段是示意图/纸板，非真实比赛动态，分布与场上完全不同，混入会污染「真实战术动作」评估。
# 单留作「示意图理解」测试集（--schematic 模式），不进主语料与正式探针。
POLLUTION_SEGS = {
    "ep10_s1", "ep11_s1", "ep13_s0", "ep14_s0", "ep14_s1",
    "ep15_s1", "ep19_s1", "ep20_s1",
}


# --------------------------------------------------------------------------
# 1. 检测层 → 结构化上下文（来自 ball_tracks.json / tracks_cf.json）
# --------------------------------------------------------------------------
def load_structured(seg_dir: Path, ball_tracks: Path = None, tracks_cf: Path = None):
    """读检测层落盘产物，抽上下文用于提示与评估。

    返回 dict：
        duration_s, n_frames,
        on_court_players (末帧场内球员数),
        team_split ({0:n, 1:n, None:n}),
        ball_handler_timeline (每帧持球者 tid 或 None),
        ball_coverage (有球帧占比),
        events (detect_primitives 真实事件列表),
    """
    if ball_tracks is None:
        ball_tracks = seg_dir / "ball_tracks.json"
    if tracks_cf is None:
        tracks_cf = seg_dir / "tracks_cf.json"

    bt = json.load(open(ball_tracks, encoding="utf-8"))
    n_frames = len(bt)
    duration_s = n_frames * 0.1  # frames.json 步长 0.1s（见 tactic_notes_batch 输出）

    # 队别统计：逐帧计进攻/防守/总计人数，取中位数（track ID 跨段碎片化成多 tid，不可直接数 distinct）
    tid_team = {}
    per_frame_off, per_frame_def, per_frame_total = [], [], []
    for fr in bt:
        off = sum(1 for p in fr["players"] if p.get("team") == 0)
        deff = sum(1 for p in fr["players"] if p.get("team") == 1)
        per_frame_off.append(off)
        per_frame_def.append(deff)
        per_frame_total.append(len(fr["players"]))
        for p in fr["players"]:
            t = p.get("team")
            if t is not None:
                tid_team[p["track_id"]] = t
    n_off = int(st.median(per_frame_off)) if per_frame_off else 0
    n_def = int(st.median(per_frame_def)) if per_frame_def else 0
    n_total = int(st.median(per_frame_total)) if per_frame_total else 0
    team_split = {0: n_off, 1: n_def, None: 0}
    last = bt[-1]["players"]

    # 持球者时间线：优先 tracks_cf（已算 ball_handler），否则用 ball_tracks 的 ball 邻近推断
    bh_timeline = [None] * n_frames
    ball_coverage = 0
    if tracks_cf.exists():
        cf = json.load(open(tracks_cf, encoding="utf-8"))
        for fr in cf["frames"]:
            bh_timeline[fr["idx"]] = fr.get("ball_handler")
            if fr.get("ball") and fr["ball"].get("box"):
                ball_coverage += 1
    else:
        for i, fr in enumerate(bt):
            b = fr.get("ball")
            if b:
                ball_coverage += 1
                # 最近球员 = 持球者候选
                best, bd = None, 1e9
                bx = (b[0] + b[2]) / 2 if isinstance(b, list) and len(b) >= 4 else None
                by = (b[1] + b[3]) / 2 if isinstance(b, list) and len(b) >= 4 else None
                if bx is None:
                    continue
                for p in fr["players"]:
                    bb = p["bbox"]
                    px, py = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                    d = abs(px - bx) + abs(py - by)
                    if d < bd:
                        bd, best = d, p["track_id"]
                bh_timeline[i] = best

    # 真实原语事件（复用既有 engine，阈值由本片段实测分布导出）
    try:
        frames, excl, ball_src = load_clip(str(seg_dir), tracks_json=str(ball_tracks))
        th = derive_thresholds(frames)
        events = detect_primitives(
            frames,
            d_screen=th["d_screen_px"],
            d_handoff=th["d_handoff_px"],
            v_cut=th["v_cut_px"],
            min_run=th["min_run"],
            disp_med=th["median_frame_disp_px"],
            med_diag=th["median_player_diag_px"],
        )
    except Exception as e:  # harness 不应因单段失败而崩溃
        events = []
        print(f"  [warn] detect_primitives 失败({seg_dir.name}): {e}")

    ctx = {
        "seg": seg_dir.name,
        "duration_s": round(duration_s, 1),
        "n_frames": n_frames,
        "on_court_players": len(last),
        "on_court_total_median": n_total,
        "team_split": team_split,
        "ball_coverage": round(ball_coverage / max(1, n_frames), 3),
        "ball_handler_timeline": bh_timeline,
        "tid_team": tid_team,
        "events": events,
    }
    return ctx


# --------------------------------------------------------------------------
# 2. YOLO → Mage-VL 提示模板（§8）
# --------------------------------------------------------------------------
def build_prompt(ctx, rel_list=None, event_types=None):
    """§8 模板：把检测层结构化结果压成自然语言先验，喂 Mage-VL 减幻觉。

    rel_list: RelateAnything 关系（TODO 未接，传 None）
    event_types: detect_primitives 事件类型集合（已真实计算）
    """
    ts = ctx["team_split"]
    n_off = ts.get(0, 0)
    n_def = ts.get(1, 0)
    # 持球者：取时间线上出现最多的 tid
    from collections import Counter
    bh_counter = Counter(t for t in ctx["ball_handler_timeline"] if t is not None)
    bh_id = bh_counter.most_common(1)[0][0] if bh_counter else None
    bh_team = _team_of(ctx, bh_id)

    rel_txt = "、".join(rel_list) if rel_list else "（RelateAnything 未接入）"
    ev_txt = "、".join(sorted(event_types)) if event_types else "（无）"

    prompt = (
        f"[上下文] 这是一段 {ctx['duration_s']}s 的 NBA 进攻回合半场画面"
        f"（已过滤观众与裁判）。\n"
        f"[注] 当前片段尚未做球场单应标定（P0 已知），坐标基于广播像素，"
        f"方向类判据（朝筐/下掩护）可能偏差，请仅基于可见画面描述。\n"
        f"[已知检测结果 · YOLO]\n"
        f"- 场上：约 {ctx.get('on_court_total_median', n_off + n_def)} 人"
        f"（进攻方 {n_off} / 防守方 {n_def} 已标定队别，其余未标定）\n"
        f"- 持球者：#{bh_id}（{bh_team}）\n"
        f"- 关键空间关系（RelateAnything）：{rel_txt}\n"
        f"- 规则事件候选：{ev_txt}\n"
        f"[任务] 描述这段进攻配合的战术：掩护类型（低位/高位/侧翼）、无球跑动路线、"
        f"持球人动向、球权转移、终结方式。指出与「已知检测结果」一致或冲突之处。\n"
        f"[约束] 只做描述，不输出最终战术标签；画面信息不足时明确说明。"
    )
    return prompt


def _team_of(ctx, tid):
    return ctx.get("tid_team", {}).get(tid, "未知队别")


# --------------------------------------------------------------------------
# 3. RelateAnything 接入（TODO，未接）
# --------------------------------------------------------------------------
def load_relate_anything(seg_dir: Path):
    """RelateAnything 空间关系接入点（分层架构理解层的补充结构化信号）。

    当前未接：RelateAnything 需单独跑（见 RelateAnything/ 与 skill relateanything-action-analysis），
    产物格式待定。返回 None，提示模板以占位符呈现，不伪造关系。
    """
    return None


# --------------------------------------------------------------------------
# 4. ASR 真值加载（标签只信 ASR）
# --------------------------------------------------------------------------
def load_asr_gold(ann_json: Path):
    """读 asr_segment_annotation.json，返回 {seg: {gold_terms:set, narration:str, cues:list}}。

    gold_terms = episode_tactics ∪ cue.term（人声战术术语，工具不猜）
    """
    data = json.load(open(ann_json, encoding="utf-8"))
    out = {}
    for s in data.get("segments", []):
        terms = set(s.get("episode_tactics") or [])
        for c in s.get("cues", []) or []:
            if c.get("term"):
                terms.add(c["term"])
        out[s["seg"]] = {
            "gold_terms": terms,
            "narration": s.get("narration", ""),
            "cues": s.get("cues", []),
            "t0": s.get("t0"),
            "t1": s.get("t1"),
        }
    return out


def load_vocab(ann_json: Path):
    """战术词表 = 全语料 episode_tactics 并集（随机基线分母）。"""
    data = json.load(open(ann_json, encoding="utf-8"))
    vocab = set()
    for s in data.get("segments", []):
        for t in (s.get("episode_tactics") or []):
            vocab.add(t)
    return vocab


# --------------------------------------------------------------------------
# 5. 双基线 + 信息量对照评估（防假完整）
# --------------------------------------------------------------------------
def evaluate(gold: set, candidate: set, vocab: set,
              corpus_majority_class: str = None, corpus_majority_acc: float = None):
    """候选集 vs ASR 真值集，报双基线 + 信息增益。

    acc        = |gold ∩ candidate| / |gold|           （候选对真值的召回）
    random_acc = |candidate| / |vocab|                 （随机抽同规模集的期望召回）
    majority_acc = corpus 级：全语料中含多数类的段占比（单段退化时由调用方传入）
    info_gain  = acc - max(random_acc, majority_acc)
    """
    g = gold or set()
    c = candidate or set()
    V = vocab or set()
    acc = len(g & c) / len(g) if g else 0.0
    random_acc = len(c) / len(V) if V else 0.0
    if corpus_majority_acc is not None:
        majority_acc = corpus_majority_acc
    elif corpus_majority_class is not None:
        majority_acc = 1.0 / len(g) if g and corpus_majority_class in g else 0.0
    else:
        majority_acc = 1.0 / len(g) if g else 0.0
    info_gain = acc - max(random_acc, majority_acc)
    return {
        "gold": sorted(g),
        "candidate": sorted(c),
        "acc": round(acc, 3),
        "random_baseline": round(random_acc, 3),
        "majority_baseline": round(majority_acc, 3),
        "info_gain": round(info_gain, 3),
        "verdict": "above_baseline" if info_gain > 0 else "at_or_below_baseline",
    }


def clip_vs_frame_info_gain(events_all):
    """信息量对照（三级验证门简化版 step2）：clip 级事件集合 vs 单帧事件集合。

    方法论（无 Mage-VL 权重时，用规则事件做 proxy 演示，结构可直接迁移到 Mage 描述）：
      - clip_types  = 整段聚合的原语类型集合（需看完整时间窗才能出现）
      - frame_types = 单帧「峰值密度帧」上同时活跃的原语类型集合（只看一帧能看到的上限）
      - gain        = |clip_types − frame_types|：只有看整段才能拿到的信息量
    真正评估时把 clip_types / frame_types 换成 Mage-VL 描述解析出的战术集即可。
    """
    def _key(e):
        return e["type"] + ("." + e["sub"] if e.get("sub") else "")

    clip_set = set(_key(e) for e in events_all)
    # 峰值密度帧：同时活跃事件数最多的帧
    if not events_all:
        return {"clip_event_types": [], "peak_frame_event_types": [],
                "clip_minus_frame": [], "gain": 0, "peak_frame": None}
    f0 = min(e["f0"] for e in events_all)
    f1 = max(e["f1"] for e in events_all)
    best_f, best_n = f0, -1
    for f in range(f0, f1 + 1):
        n = sum(1 for e in events_all if e["f0"] <= f <= e["f1"])
        if n > best_n:
            best_n, best_f = n, f
    frame_set = set(_key(e) for e in events_all if e["f0"] <= best_f <= e["f1"])
    return {
        "clip_event_types": sorted(clip_set),
        "peak_frame_event_types": sorted(frame_set),
        "peak_frame": best_f,
        "clip_minus_frame": sorted(clip_set - frame_set),
        "gain": len(clip_set - frame_set),
    }


def build_alignment_table(asr_terms, rule_event_types, mage_desc=None):
    """对齐表（老程交付要求）：Mage 描述 | ASR 真值 | 规则事件 三路并列。

    无权重时 mage_desc=None → 该列标 pending；ASR 与规则事件为真实磁盘数据。
    返回 dict，run_segment 负责打印可读表 + 可选落盘 JSON。
    """
    return {
        "mage_desc": mage_desc,  # None → pending weights
        "asr_terms": sorted(asr_terms),
        "rule_event_types": sorted(rule_event_types),
        "aligned_in_asr": sorted(set(rule_event_types) & set(asr_terms)),
    }


# --------------------------------------------------------------------------
# 6. Mage-VL 推理接口（真实实现：BF16 + frames 后端，M4 MPS）
# --------------------------------------------------------------------------
def _load_mage(weights: Path):
    """懒加载 Mage-VL 单例（权重 ~176s，批量必须只加载一次，否则每段重载）。"""
    global _MAGE_MODEL, _MAGE_PROCESSOR
    if _MAGE_MODEL is not None:
        return _MAGE_MODEL, _MAGE_PROCESSOR
    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.bfloat16
    print(f"  [mage] 加载权重 {weights} → device={device} dtype={dtype}（首次约需 2-3 分钟）")
    processor = AutoProcessor.from_pretrained(str(weights), trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(weights), trust_remote_code=True, torch_dtype=dtype, low_cpu_mem_usage=True,
    ).to(device).eval()
    _MAGE_MODEL, _MAGE_PROCESSOR = model, processor
    print("  [mage] 权重加载完成")
    return model, processor


def _sample_frames_dir(frames_dir: Path, num_frames: int, frame_size=None):
    """从段目录的 frames/（逐帧 f*.jpg）均匀抽 num_frames 帧，缩到 frame_size 返回 PIL 列表。

    缩帧是本机 16GB 的**保命操作**：总 patch 数（而非单纯帧数）驱动显存/内存工作集，
    不缩就会换页抖动（实测 1280x720×16 帧 swap 打满）。
    """
    from PIL import Image
    files = sorted(frames_dir.glob("*.jpg"))
    if not files:
        return []
    import numpy as np
    idx = np.linspace(0, len(files) - 1, min(num_frames, len(files)), dtype=int)
    out = []
    for i in idx:
        try:
            im = Image.open(files[int(i)]).convert("RGB")
            if frame_size:
                im = im.resize(tuple(frame_size), Image.BILINEAR)
            out.append(im)
        except Exception:
            continue
    return out


def _sample_frames_video(clip_path: Path, num_frames: int, frame_size=None):
    """从 mp4 均匀抽帧（复刻 load test 的 frames 后端行为），可缩到 frame_size。"""
    import cv2
    import numpy as np
    from PIL import Image
    cap = cv2.VideoCapture(str(clip_path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if n <= 0:
        cap.release()
        return []
    idx = np.linspace(0, n - 1, min(num_frames, n), dtype=int)
    out = []
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            im = Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
            if frame_size:
                im = im.resize(tuple(frame_size), Image.BILINEAR)
            out.append(im)
    cap.release()
    return out


def mage_vl_infer(clip_path: Path, prompt: str, weights: Path = DEFAULT_MAGE_WEIGHTS,
                  num_frames: int = None, max_new_tokens: int = None):
    """调用 Mage-VL 生成战术描述（真实实现，BF16/frames 后端）。

    clip_path 可以是段目录的 frames/ 目录（逐帧 jpg）或一个 mp4。
    prompt 为 §8 生成的 YOLO→Mage-VL 结构化提示，作为用户指令文本喂入（融合档②）。
    权重缺失返回 None（禁假完整）；推理失败抛出由调用方决定是否降级。
    """
    if not Path(weights).exists():
        return None  # 不伪造输出（禁假完整）
    num_frames = num_frames or MAGE_NUM_FRAMES
    max_new_tokens = max_new_tokens or MAGE_MAX_TOKENS
    import torch
    model, processor = _load_mage(Path(weights))
    device = next(model.parameters()).device

    p = Path(clip_path)
    if p.is_dir():
        frames = _sample_frames_dir(p, num_frames, frame_size=MAGE_FRAME_SIZE)
    else:
        frames = _sample_frames_video(p, num_frames, frame_size=MAGE_FRAME_SIZE)
    if not frames:
        return None

    messages = [{"role": "user", "content": [
        {"type": "video"},
        {"type": "text", "text": prompt},
    ]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], videos=frames, return_tensors="pt", padding=True)
    inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    if "pixel_values" in inputs:
        inputs["pixel_values"] = inputs["pixel_values"].to(model.dtype)

    gen_kw = {"max_new_tokens": max_new_tokens, "do_sample": MAGE_DO_SAMPLE}
    if MAGE_DO_SAMPLE and MAGE_TEMPERATURE:
        gen_kw["temperature"] = MAGE_TEMPERATURE
    if MAGE_REPETITION_PENALTY:
        gen_kw["repetition_penalty"] = MAGE_REPETITION_PENALTY
    if MAGE_NO_REPEAT_NGRAM:
        gen_kw["no_repeat_ngram_size"] = MAGE_NO_REPEAT_NGRAM

    with torch.inference_mode():
        out = model.generate(**inputs, **gen_kw)
    n_ctx = inputs["input_ids"].shape[1]
    desc = processor.tokenizer.decode(out[0, n_ctx:], skip_special_tokens=True)
    # 长批量下多段连续推理会让 MPS 分配器缓存/碎片累积，实测跑到第 7 段就换页抖动
    # （swap 打满、空闲率跌回 27%）。每段推理完立即归还 MPS 缓存。
    try:
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass
    return desc.strip()


# 8. 退化判据（可证伪，供"解码策略级联"触发升级用）
# --------------------------------------------------------------------------
_TEMPLATE_PREFIXES = ("进攻配合战术描述如下：", "战术描述：", "[战术描述]", "[任务输出]", "战术描述如下：")


def is_degenerate(desc, min_chars=25, rep_dup_thresh=0.35):
    """判定 Mage 描述是否退化。返回 (bool, reason)。

    三条可证伪判据（均由实测观察定义，非拍脑袋）：
      too_short          : 有效字符 < min_chars
      template_header_only: 命中模板前缀且前缀之后内容不足（被"1./2."编号勾住只吐标题）
      repetitive_X.XX    : 4-gram 重复率 > rep_dup_thresh（greedy 复读）
    """
    core = (desc or "").strip()
    if len(core) < min_chars:
        return True, f"too_short({len(core)})"
    for pref in _TEMPLATE_PREFIXES:
        if core.startswith(pref):
            rest = core[len(pref):].strip()
            if len(rest) < 15:
                return True, "template_header_only"
    grams = [core[i:i + 4] for i in range(len(core) - 3)]
    if grams:
        dup = 1 - len(set(grams)) / len(grams)
        if dup > rep_dup_thresh:
            return True, f"repetitive({dup:.2f})"
    return False, "ok"


# --------------------------------------------------------------------------
# 9. 主流程
# --------------------------------------------------------------------------
def run_segment(seg_dir: Path, ann_json: Path, do_magevl: bool = False,
                 include_pollution: bool = False, out_json: Path = None):
    seg_dir = Path(seg_dir)
    ann_json = Path(ann_json)
    seg = seg_dir.name

    # 图版段剔除（老程裁定：不进主战术语料）
    if seg in POLLUTION_SEGS and not include_pollution:
        print(f"\n=== 段 {seg} === [SKIP] 图版/战术讲解纸板段，已剔除主战术语料")
        return {"seg": seg, "skipped": "pollution"}

    print(f"\n=== 段 {seg} ===")
    ctx = load_structured(seg_dir)
    print(f"  时长 {ctx['duration_s']}s / {ctx['n_frames']}帧 / 球覆盖 {ctx['ball_coverage']}")
    print(f"  真实原语事件数: {len(ctx['events'])}")

    event_types = set(
        e["type"] + ("." + e["sub"] if e.get("sub") else "") for e in ctx["events"]
    )
    rel = load_relate_anything(seg_dir)
    prompt = build_prompt(ctx, rel_list=rel, event_types=event_types)
    print("\n--- YOLO→Mage-VL 提示（§8）---")
    print(prompt)

    # ASR 真值
    gold_map = load_asr_gold(ann_json)
    vocab = load_vocab(ann_json)
    g = gold_map.get(seg, {}).get("gold_terms", set())
    print(f"\n  ASR 真值战术术语: {sorted(g) if g else '（本段无 ASR 标注）'}")

    # corpus 级多数类基线（防假完整铁律）
    from collections import Counter
    corp_counter = Counter()
    for s in gold_map.values():
        for t in s["gold_terms"]:
            corp_counter[t] += 1
    maj_class = corp_counter.most_common(1)[0][0] if corp_counter else None
    n_seg = max(1, len(gold_map))
    maj_acc = sum(1 for s in gold_map.values() if maj_class in s["gold_terms"]) / n_seg

    # 规则事件作为 candidate proxy（演示 harness；非 Mage-VL 输出）
    cand = set(e["type"] for e in ctx["events"])
    ev = evaluate(g, cand, vocab, corpus_majority_class=maj_class, corpus_majority_acc=maj_acc)
    print("\n--- 双基线 + 信息量对照（candidate=规则原语类型, proxy）---")
    print(f"  acc={ev['acc']}  random={ev['random_baseline']}  majority={ev['majority_baseline']}  gain={ev['info_gain']}  -> {ev['verdict']}")

    # 单帧 vs clip 信息量对照（三级验证门 step2）
    ig = clip_vs_frame_info_gain(ctx["events"])
    print("\n--- 信息量对照：单帧 vs clip ---")
    print(f"  clip 级事件类型({len(ig['clip_event_types'])}): {ig['clip_event_types']}")
    print(f"  峰值帧#{ig['peak_frame']} 单帧事件类型({len(ig['peak_frame_event_types'])}): {ig['peak_frame_event_types']}")
    print(f"  仅 clip 级可见(需整段): {ig['clip_minus_frame']}  → 增益={ig['gain']} 类")
    print(f"  [判定] {'clip 有真实增益' if ig['gain'] > 0 else 'clip 无增益（proxy）'}（proxy：规则事件；接 Mage 后替换战术集重算）")

    # 对齐表：Mage 描述 | ASR | 规则事件
    mage_desc = None
    deg = None
    if do_magevl:
        # 段目录无 clip.mp4，实际逐帧 jpg 在 frames/（frames 后端输入）
        p_infer = prompt
        if MAGE_SIMPLE_PROMPT:
            # 去结构化编号模板（"1./2."会诱导模型只吐标题后收尾，实测退化根因之一）
            p_infer = ("用连贯的一段话描述这段 NBA 进攻回合发生了什么：掩护、传球、跑位和终结。"
                       "不要分点编号，不要重复句子，一句话说完。")
        mage_desc = mage_vl_infer(seg_dir / "frames", p_infer)
        if mage_desc is not None:
            bad, why = is_degenerate(mage_desc)
            deg = {"degenerate": bad, "reason": why}
            print(f"  [退化判定] degenerate={bad} reason={why}")
    tbl = build_alignment_table(g, cand, mage_desc=mage_desc)
    print("\n--- 对齐表：Mage 描述 | ASR 真值 | 规则事件 ---")
    # 🔴 防御：模型输出常含换行，直接 print 再配 grep 只看得到第一行，
    #    会把"标题+\n+正文"误读成"只吐模板标题"（2026-10-04 我踩过，误判成大面积退化）。
    #    这里把换行压平成空格后全文打印，保证肉眼/日志都能读到完整内容。
    _flat = (tbl["mage_desc"] or "").replace("\r", " ").replace("\n", " ")
    print(f"  Mage描述 : {_flat if _flat else '（pending weights）'}")
    print(f"  ASR真值  : {tbl['asr_terms']}")
    print(f"  规则事件 : {tbl['rule_event_types']}")
    print(f"  规则∩ASR : {tbl['aligned_in_asr'] or '（空：规则原语≠战术名，恰证 Mage 语义层必要）'}")

    result = {"seg": seg, "ctx": {k: ctx[k] for k in (
        "duration_s", "n_frames", "ball_coverage", "on_court_total_median",
        "team_split", "events")}, "prompt": prompt, "eval": ev,
        "info_gain_clip_vs_frame": ig, "alignment": tbl,
        "mage_degenerate": deg, "asr_gold": sorted(g) if g else []}
    if out_json:
        out_json = Path(out_json)
        prev = json.load(open(out_json, encoding="utf-8")) if out_json.exists() else []
        prev.append(result)
        json.dump(prev, open(out_json, "w", encoding="utf-8"),
                   ensure_ascii=False, indent=2, default=str)
        print(f"  [out] 已追加到 {out_json}")
    return result


def run_batch(seg_root: Path, ann_json: Path, out_json: Path = None,
              include_pollution: bool = False, seg_filter: str = None,
              do_magevl: bool = False):
    """批量跑所有干净段（排除图版段），收集对齐表 + 评估，落盘 JSON。

    seg_filter: 正则，只处理名字匹配的段（如 ^(ep1[0-9]|ep20)_s[01]$），
                用于把 177 段全库收敛到目标子集（如 ep10-20 的 14 干净段）。
    """
    seg_root = Path(seg_root)
    rows = []
    if out_json:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    for d in sorted(seg_root.iterdir()):
        if not d.is_dir():
            continue
        if seg_filter and not re.search(seg_filter, d.name):
            continue
        if d.name in POLLUTION_SEGS and not include_pollution:
            print(f"[batch] skip 图版段 {d.name}")
            continue
        r = run_segment(d, ann_json, do_magevl=do_magevl,
                        include_pollution=include_pollution, out_json=None)
        rows.append(r)
        # 增量落盘：每段后立即写，避免进程被中途停止（换页卡死/手动中断）丢掉已跑结果
        if out_json:
            json.dump(rows, open(Path(out_json), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2, default=str)
            print(f"  [batch] 已增量落盘 {out_json}（{len(rows)} 段）")
    if out_json:
        print(f"\n[batch] 已写 {out_json}（{len(rows)} 段）")
    return rows


def main():
    ap = argparse.ArgumentParser(description="Mage-VL 理解层探针骨架（无权重可跑 harness）")
    ap.add_argument("--seg-dir", default=None, help="段目录(含 ball_tracks.json/tracks_cf.json)")
    ap.add_argument("--seg-root", default=str(AW / "tactic_notes_batch_full" / "segments"),
                    help="批量模式：段根目录（默认 full segments，唯一有逐帧 frames 的批次）")
    ap.add_argument("--seg-filter", default=None,
                    help="批量段名正则过滤（如 ^(ep1[0-9]|ep20)_s[01]$ 收敛到 ep10-20）")
    ap.add_argument("--mage-frames", type=int, default=None, help="Mage-VL 抽帧数（默认全局 MAGE_NUM_FRAMES）")
    ap.add_argument("--mage-frame-size", default=None,
                    help="帧尺寸 WxH（如 512x288）；缩帧是本机 16GB 免换页的关键杠杆，默认 512x288")
    ap.add_argument("--mage-rep-penalty", type=float, default=None, help="repetition_penalty（治复读，建议1.1-1.3）")
    ap.add_argument("--mage-no-repeat-ngram", type=int, default=None, help="no_repeat_ngram_size（建议3-5）")
    ap.add_argument("--mage-temperature", type=float, default=None, help="配合 --do-sample 的温度")
    ap.add_argument("--do-sample", action="store_true", help="改用采样解码（默认 greedy）")
    ap.add_argument("--mage-simple-prompt", action="store_true",
                    help="用短指令替代 §8 结构化编号模板（去「1./2.」诱导）")
    ap.add_argument("--mage-max-tokens", type=int, default=None, help="Mage-VL 生成上限 token（默认全局）")
    ap.add_argument("--asr-annotation", default=str(AW / "asr_segment_annotation.json"))
    ap.add_argument("--do-magevl", action="store_true", help="尝试调用 Mage-VL（需权重，默认关闭）")
    ap.add_argument("--out", default=None, help="追加/批量结果落盘 JSON 路径")
    ap.add_argument("--include-pollution", action="store_true",
                    help="含图版/战术讲解纸板段（默认剔除主战术语料）")
    ap.add_argument("--batch", action="store_true", help="批量跑 seg-root 下所有干净段")
    ap.add_argument("--smoke", action="store_true", help="冒烟：跑 ep10_s0 验证 harness 接线")
    a = ap.parse_args()

    global MAGE_NUM_FRAMES, MAGE_MAX_TOKENS, MAGE_FRAME_SIZE
    global MAGE_DO_SAMPLE, MAGE_TEMPERATURE, MAGE_REPETITION_PENALTY
    global MAGE_NO_REPEAT_NGRAM, MAGE_SIMPLE_PROMPT
    if a.mage_rep_penalty:
        MAGE_REPETITION_PENALTY = a.mage_rep_penalty
    if a.mage_no_repeat_ngram:
        MAGE_NO_REPEAT_NGRAM = a.mage_no_repeat_ngram
    if a.mage_temperature:
        MAGE_TEMPERATURE = a.mage_temperature
    if a.do_sample:
        MAGE_DO_SAMPLE = True
    if a.mage_simple_prompt:
        MAGE_SIMPLE_PROMPT = True
        MAGE_NUM_FRAMES = a.mage_frames
    if a.mage_max_tokens:
        MAGE_MAX_TOKENS = a.mage_max_tokens
    if a.mage_frame_size:
        w, h = a.mage_frame_size.lower().split("x")
        MAGE_FRAME_SIZE = (int(w), int(h))
    print(f"[config] frames={MAGE_NUM_FRAMES} frame_size={MAGE_FRAME_SIZE} "
          f"max_tokens={MAGE_MAX_TOKENS}")

    if a.smoke:
        seg = AW / "tactic_notes_batch_fix1" / "segments" / "ep10_s0"
        run_segment(seg, Path(a.asr_annotation), do_magevl=a.do_magevl,
                    include_pollution=a.include_pollution, out_json=Path(a.out) if a.out else None)
        return

    if a.batch:
        run_batch(Path(a.seg_root), Path(a.asr_annotation),
                  out_json=Path(a.out) if a.out else None,
                  include_pollution=a.include_pollution,
                  seg_filter=a.seg_filter, do_magevl=a.do_magevl)
        return

    if not a.seg_dir:
        ap.error("--seg-dir 必填（或 --smoke / --batch）")
    run_segment(Path(a.seg_dir), Path(a.asr_annotation), do_magevl=a.do_magevl,
                include_pollution=a.include_pollution, out_json=Path(a.out) if a.out else None)


if __name__ == "__main__":
    main()
