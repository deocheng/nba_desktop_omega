"""NBACore v8 — Tactics Engine 动画/帧生成（Layer 2，T05）。

确定性线性插值生成逐帧序列（球员坐标帧 + 篮球坐标帧 + 事件标注）。
固定帧率，无缓动。所有坐标已在 coords 层映射为 SVG 像素。
前端（Layer 4）仅消费本层输出的帧 JSON，禁止任何坐标计算。

两条入口（与 PBP 回放共用同一 ReplayFrame 结构）：
    build_frames(events, fps)              → PBP 解析事件 → 逐帧
    build_frames_from_template(tpl, fps)   → 战术模板 → 逐帧
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from backend.services.tactics_engine import coords
from backend.services.tactics_engine.schemas import TacticTemplate

# 事件标注显示时长（秒），超出后淡出
ANNOT_HOLD_S: float = 1.5

# 逐段帧数硬上限：控制回放总体积，避免一场 ~600 事件比赛产生数万帧。
# 旧逻辑每段 n_frames = round(dur * fps) = round(2.0 * 30) = 60 帧，导致
# ~36k 帧 / ~89MB 的响应体，浏览器加载失败。
# 前端 rAF 基于 meta.fps 推进，并不要求每段 60 张预计算帧；8 张已足够线性
# 插值下顺滑播放，且严格保持帧结构（t/players/ball/annotations/event_index）。
MAX_FRAMES_PER_SEGMENT: int = 8

# 整体帧数软上限：自适应下调逐段帧数，保证「任意场次」总帧数 <= TARGET_TOTAL_FRAMES
# （事件更多的比赛自动更稀，但播放依旧连贯）。用于满足回放响应 < 15MB 的硬指标。
# 总帧数 ≈ n_segments * seg_cap + 1，故 seg_cap 自适应为 (TARGET-1) // n_segments。
TARGET_TOTAL_FRAMES: int = 4000


def _lerp(a: Tuple[float, float], b: Tuple[float, float], t: float) -> Tuple[float, float]:
    """线性插值；t∈[0,1]。"""
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _lerp_along_path(
    pts: List[Tuple[float, float]], t: float
) -> Tuple[float, float]:
    """沿路径点序列按等参数 t∈[0,1] 分段线性插值。"""
    if not pts:
        return (0.0, 0.0)
    if len(pts) == 1:
        return pts[0]
    seg = max(0, min(int(t * (len(pts) - 1)), len(pts) - 2))
    local = t * (len(pts) - 1) - seg
    return _lerp(pts[seg], pts[seg + 1], local)


# ───────────────────────── PBP 回放帧生成 ─────────────────────────
def build_frames(events: List, fps: int = 30) -> List[dict]:
    """由解析事件生成逐帧序列（确定性）。"""
    if not events:
        return []
    fps = max(1, int(fps))
    n = len(events)
    times = [e.global_t for e in events]
    # 自适应逐段帧数上限：保证总帧数不超过 TARGET_TOTAL_FRAMES（与事件数无关）。
    # 旧逻辑每段无上限 -> 一场 ~600 事件比赛 ~36k 帧 / ~89MB，前端加载失败。
    # 通过 seg_cap 把每段帧数压到 MAX_FRAMES_PER_SEGMENT 以内，并进一步按事件数
    # 自适应收紧，确保任意场次总帧数 <= TARGET_TOTAL_FRAMES（硬指标 < 15MB）。
    n_segments = max(1, n - 1)
    seg_cap = MAX_FRAMES_PER_SEGMENT
    if TARGET_TOTAL_FRAMES and n_segments > 0:
        # 总帧数 ≈ n_segments * seg_cap + 1，故 seg_cap 上限为 (TARGET-1)//n_segments
        seg_cap = min(seg_cap, max(1, (TARGET_TOTAL_FRAMES - 1) // n_segments))
    frames: List[dict] = []

    for i in range(n - 1):
        e0, e1 = events[i], events[i + 1]
        dur = max(0.0, times[i + 1] - times[i])
        # 每段帧数 = min(round(dur*fps), seg_cap)：既保留线性插值的连贯，
        # 又把体量压到满足 < 15MB 的硬指标（帧结构不变，前端零改动即可消费）。
        n_frames = max(1, min(int(round(dur * fps)), seg_cap))
        for f in range(0, n_frames + 1):
            if i > 0 and f == 0:
                continue  # 跳过与上段末帧重复的帧
            frac = f / n_frames if n_frames else 0.0
            t = times[i] + dur * frac
            # 球员插值
            players: List[dict] = []
            sn0, sn1 = e0.snapshot, e1.snapshot
            for k in set(sn0) | set(sn1):
                if k in sn0 and k in sn1:
                    p0, p1 = sn0[k], sn1[k]
                    x = p0["x_px"] + (p1["x_px"] - p0["x_px"]) * frac
                    y = p0["y_px"] + (p1["y_px"] - p0["y_px"]) * frac
                    players.append({**p1, "x_px": round(x, 2), "y_px": round(y, 2)})
                elif k in sn0:
                    players.append(dict(sn0[k]))
                else:
                    players.append(dict(sn1[k]))
            # 篮球插值：按「段起始持球人」e0.ball["holder"] 的精灵插值位置跟踪，
            # 而非直接 e0.ball → e1.ball（否则球会飞向非持球 actor）。
            # holder 为 None（投篮出手后 / loose ball）时停在段起始篮球位置。
            b0 = e0.ball
            holder = b0.get("holder")
            if holder and holder in sn0 and holder in sn1:
                p0, p1 = sn0[holder], sn1[holder]
                bx = p0["x_px"] + (p1["x_px"] - p0["x_px"]) * frac
                by = p0["y_px"] + (p1["y_px"] - p0["y_px"]) * frac
            elif holder and holder in sn0:
                bx, by = sn0[holder]["x_px"], sn0[holder]["y_px"]
            elif holder and holder in sn1:
                bx, by = sn1[holder]["x_px"], sn1[holder]["y_px"]
            else:
                # 无持球人（出手/loose ball）→ 球停在段起始点，不飞向他人
                bx, by = b0["x_px"], b0["y_px"]
            ball = {"x_px": round(bx, 2), "y_px": round(by, 2), "holder": holder}
            # 标注：事件 i 的标注在 ANNOT_HOLD_S 内持续显示（支持多气泡）
            annotations: List[dict] = []
            for a in (e0.annotation or []):
                if (t - times[i]) <= ANNOT_HOLD_S:
                    annotations.append({"type": a["type"], "text": a["text"],
                                        "x_px": a["x_px"], "y_px": a["y_px"]})
            frames.append({
                "t": round(t, 3),
                "players": players,
                "ball": ball,
                "annotations": annotations,
                "event_index": i + 1 if f > 0 else i,
            })
    return frames


# ───────────────────────── 战术模板帧生成 ─────────────────────────
def _template_frame(
    event_index: int,
    tpl: TacticTemplate,
    positions: Dict[int, Tuple[float, float]],
    ball_pos: Tuple[float, float],
    holder: Optional[str],
    t: float,
) -> dict:
    """构造单帧（球员来自 formation 映射，篮球来自 ball_pos 映射）。"""
    players = []
    for s in tpl.formation:
        px, py = coords.map_xy_to_svg(*positions.get(s.slot, (s.x, s.y)))
        players.append({
            "player_id": f"tpl_{s.slot}",
            "label": s.label,
            "team": s.team,
            "color": coords.HOME_COLOR if s.team == "home" else coords.AWAY_COLOR,
            "x_px": round(px, 2),
            "y_px": round(py, 2),
            "pos_source": "real",
        })
    bpx, bpy = coords.map_xy_to_svg(*ball_pos)
    ball = {"x_px": round(bpx, 2), "y_px": round(bpy, 2), "holder": holder}
    return {
        "t": round(t, 3),
        "players": players,
        "ball": ball,
        "annotations": [],
        "event_index": event_index,
    }


def build_frames_from_template(tpl: TacticTemplate, fps: int = 30) -> List[dict]:
    """将战术模板展开为逐帧序列（与 PBP 同一 ReplayFrame 结构）。"""
    fps = max(1, int(fps))
    positions: Dict[int, Tuple[float, float]] = {
        s.slot: (float(s.x), float(s.y)) for s in tpl.formation
    }
    ball_pos: Tuple[float, float] = (
        float(tpl.ball_start[0]), float(tpl.ball_start[1])
    )
    frames: List[dict] = []
    cur_t = 0.0

    # 初始帧
    frames.append(_template_frame(0, tpl, positions, ball_pos, None, 0.0))

    for step in tpl.steps:
        path_pts: List[Tuple[float, float]] = [
            positions.get(step.actor_slot, (0.0, 0.0))
        ] + list(step.path)
        if step.ball_to is None:
            ball_target = ball_pos
        elif isinstance(step.ball_to, int):
            ball_target = positions.get(step.ball_to, ball_pos)
        else:
            ball_target = (float(step.ball_to[0]), float(step.ball_to[1]))
        seg_dur = max(0.1, float(step.duration_s))
        n_frames = max(1, int(round(seg_dur * fps)))
        for f in range(1, n_frames + 1):
            frac = f / n_frames
            actor_pos = _lerp_along_path(path_pts, frac)
            positions[step.actor_slot] = actor_pos
            ball_pos = _lerp(ball_pos, ball_target, frac)
            holder = step.ball_to if isinstance(step.ball_to, int) else None
            t = cur_t + seg_dur * frac
            frames.append(_template_frame(
                step.index + 1, tpl, positions, ball_pos, holder, t))
        cur_t += seg_dur
    return frames
