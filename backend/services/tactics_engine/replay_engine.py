"""NBACore v8 — Tactics Engine PBP 回放引擎（Layer 2，T04）。

流程：
    1. build_event_sequence  → 经 db 批量取该场全部 PBP 事件（时间序）
    2. resolve_positions     → 逐事件解析每位球员像素坐标，落地 last-known 占位策略
    3. build_frames*         → 委托 animation 线性插值生成逐帧序列

严格四层隔离：本模块只做计算，所有 DB 访问经 db.py（core.db.batch_query）。

占位策略（架构 §8.4 / PRD §4.2 硬性）：
    - 投篮（makes/misses）一律视为投篮：渲染 MAKE/MISS 标注 + 球脱手（holder=None）
      - 坐标 (x,y)≠(0,0) → 真实 coords.map_xy_to_svg，pos_source='real'
      - 坐标缺失 (0,0) → 球落向篮筐 coords.RIM_PX（绝不为 (0,0)），pos_source='default'
    - 非投篮且 actor 有历史坐标 → 延续 last-known，pos_source='last_known'
    - actor 首次出现（无历史）→ 球场语义默认位（本方半场底线附近），pos_source='default'
    - 前端不感知 (0,0)；帧 JSON 中所有坐标均为已解析像素
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from backend.services.tactics_engine import coords
from backend.services.tactics_engine.db import load_pbp_events
from backend.services.tactics_engine.schemas import PbPEvent

# 时间/占位策略常量
DEFAULT_EVENT_S: float = 2.0    # 无 clock 差时（如换节）的默认事件时长
MIN_STEP_S: float = 0.5         # 同 clock 多事件的最小步进
MAX_STEP_S: float = 120.0       # 单步最大时长（避免节间巨大跳变）


@dataclass
class ResolvedEvent:
    """解析后的单事件（含像素坐标快照 + 篮球状态 + 标注 + 单调全局时间）。"""

    event_index: int
    game_id: str
    season: str
    period: int
    clock_seconds: float
    event_type: str
    subtype: str
    action_verb: str
    player: str
    team_abbr: str
    x: int
    y: int
    dist: int
    actor_px: Tuple[float, float]
    actor_pos_source: str
    snapshot: Dict[str, dict]
    ball: dict
    global_t: float = 0.0
    annotation: List[dict] = field(default_factory=list)


def build_event_sequence(game_id: str, season) -> List[PbPEvent]:
    """批量读取并按时间序组装 PBP 事件序列。"""
    return load_pbp_events(game_id, season)


def _initials(name: str) -> str:
    """从球员名生成圆圈标签（姓名缩写）。"""
    if not name:
        return "?"
    parts = name.replace(".", " ").split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:3].upper()


def _sprite(player: str, role_color: dict, px: Tuple[float, float], pos_source: str) -> dict:
    """构造 PlayerSprite 形态 dict。"""
    return {
        "player_id": player,
        "label": _initials(player),
        "team": role_color["role"],
        "color": role_color["color"],
        "x_px": px[0],
        "y_px": px[1],
        "pos_source": pos_source,
    }


def _hash_spread(name: str) -> float:
    """确定性 y 偏移（同球员稳定、不同球员分散），避免重叠。"""
    h = abs(hash(name or "x")) % 341  # 0..340
    return float(h) - 170.0  # [-170, 170]


def _rim_attacked(rc: dict) -> "tuple[float, float]":
    """按队角色取进攻篮筐（home 攻右筐 / away 攻左筐，广播视角）。"""
    return coords.RIM_PX_RIGHT if rc.get("role") == "home" else coords.RIM_PX_LEFT


def _toward_midcourt(rim_px: "tuple[float, float]", dist_px: float) -> float:
    """从篮筐沿 x 向中场方向退 dist_px（home 右筐 x 变小 / away 左筐 x 变大）。"""
    return rim_px[0] - dist_px if rim_px[0] > 470.0 else rim_px[0] + dist_px


def _reconstruct_shot_px(rc: dict, desc: str, player: str) -> "tuple[float, float]":
    """BR 无坐标时，按投篮语义重建近似投篮点（全场广播视角，绝不冒充 real）。"""
    rim = _rim_attacked(rc)
    d = (desc or "").lower()
    if "three" in d or "3-pt" in d or "3pt" in d or "3 point" in d:
        dist_px = 230.0  # 三分线 ~23ft → ~230px
    elif ("layup" in d or "dunk" in d or "tip" in d or "putback" in d
          or "alley" in d or "hook" in d or "finger" in d):
        dist_px = 18.0  # 篮下
    elif "free throw" in d:
        dist_px = 150.0  # 罚球线 ~15ft
    else:
        dist_px = 120.0  # 中距离
    sx = _toward_midcourt(rim, dist_px)
    sy = 250.0 + _hash_spread(player or "shot")
    sx = max(20.0, min(920.0, sx))
    sy = max(40.0, min(460.0, sy))
    return (sx, sy)


def _reconstruct_zone_px(rc: dict, kind: str, player: str) -> "tuple[float, float]":
    """BR 无坐标时，非投篮事件的近似区域位（篮板/中场/半场）。"""
    rim = _rim_attacked(rc)
    if (kind or "") in ("rebound", "foul"):
        dist_px = 45.0  # 篮下附近
    elif (kind or "") in ("turnover", "steal"):
        dist_px = 210.0  # 中场推进
    else:
        dist_px = 160.0  # 半场进攻区
    sx = _toward_midcourt(rim, dist_px)
    sy = 250.0 + _hash_spread(player or kind or "z")
    sx = max(20.0, min(920.0, sx))
    sy = max(40.0, min(460.0, sy))
    return (sx, sy)


def resolve_positions(events: List[PbPEvent], full_court: bool = False) -> List[ResolvedEvent]:
    """逐事件解析每位球员像素坐标，落地 last-known 占位策略。

    full_court=False（默认）：半场映射（coords.map_xy_to_svg），供战术板模板
        与既有单测（Bug1/Bug2 回归）。
    full_court=True：全场广播视角映射（coords.map_xy_to_svg_full + 双篮筐兜底
        nearest_rim），PBP 回放恒走此路径。
    """
    known: Dict[str, dict] = {}            # player -> sprite dict
    team_role: Dict[str, dict] = {}        # team_abbr -> {role, color}
    role_count = {"home": 0, "away": 0}
    default_idx = {"home": 0, "away": 0}
    # 坐标映射器随 full_court 切换（唯一映射点，确定性、无副作用）
    mapper = coords.map_xy_to_svg_full if full_court else coords.map_xy_to_svg
    init_x = coords.FULL_SVG_W / 2.0 if full_court else coords.SVG_W / 2.0
    init_y = coords.FULL_SVG_H / 2.0 if full_court else coords.SVG_H - 40.0
    ball = {"x_px": init_x, "y_px": init_y, "holder": None}

    resolved: List[ResolvedEvent] = []
    prev_t = 0.0
    prev_clock = None
    prev_period = None

    for ev in events:
        team_abbr = ev.team or ""
        # 队角色分配：首个出现→home，其次→away
        if team_abbr and team_abbr not in team_role:
            role = "home" if role_count["home"] == 0 else "away"
            role_count[role] += 1
            team_role[team_abbr] = {
                "role": role,
                "color": coords.HOME_COLOR if role == "home" else coords.AWAY_COLOR,
            }
        rc = team_role.get(team_abbr, {"role": "away", "color": coords.AWAY_COLOR})

        actor = ev.player or ""
        # Bug 2 修复：所有 makes/misses 都视为投篮（即使坐标为 (0,0) 也要渲染
        # MAKE/MISS 标注并让球落向篮筐）；仅「真实坐标」与否影响 pos_source。
        is_shot_verb = ev.action_verb in ("makes", "misses")
        has_real_coords = (ev.x != 0 or ev.y != 0)
        actor_px = (coords.SVG_W / 2.0, coords.SVG_H - 40.0)
        actor_pos_source = "default"

        if is_shot_verb:
            if has_real_coords:
                actor_px = mapper(ev.x, ev.y)
                actor_pos_source = "real"
                if actor:
                    known[actor] = _sprite(actor, rc, actor_px, "real")
            else:
                # BR 源 PBP 无 x/y（已实测 BBRef 全 NULL）：按进攻半场 + 事件语义
                # 重建近似投篮点（绝不冒充 real，pos_source='reconstructed'）。
                # 更新 known[actor]，使球/持球人跟随、后续 last-known 也合理
                # （替代原「球飞向篮筐」占位，那会让整场动画失真）。
                actor_px = _reconstruct_shot_px(rc, ev.description, actor) if actor else coords.nearest_rim(ev.x, ev.y)
                actor_pos_source = "reconstructed"
                if actor:
                    known[actor] = _sprite(actor, rc, actor_px, "reconstructed")
        elif actor:
            if actor in known:
                sp = known[actor]
                actor_px = (sp["x_px"], sp["y_px"])
                actor_pos_source = "last_known"
                # Bug 1 配套：持球事件也把持球人站位刷新为当前解析站位，
                # 保证 ball 与 holder 精灵位置一致（球真正跟随持球人移动）。
                known[actor] = _sprite(actor, rc, actor_px, actor_pos_source)
            else:
                # BR 无坐标：按队进攻半场 + 事件类型重建近似区域位
                # （替代原「全局默认堆中心底线」幽灵位，使球员分布合理、球随持球人移动）
                actor_px = _reconstruct_zone_px(rc, ev.action_verb, actor)
                actor_pos_source = "reconstructed"
                known[actor] = _sprite(actor, rc, actor_px, "reconstructed")

        # 标注（同一事件可有多个气泡，如命中+助攻同时显示）
        anns: List[dict] = []
        if ev.action_verb == "makes":
            anns.append({"type": "MAKE", "text": "✅", "x_px": actor_px[0], "y_px": actor_px[1]})
            if ev.player2:
                p2 = ev.player2
                p2px = known.get(p2)
                px = (p2px["x_px"], p2px["y_px"]) if p2px else actor_px
                anns.append({"type": "AST", "text": "AST", "x_px": px[0], "y_px": px[1]})
        elif ev.action_verb == "misses":
            anns.append({"type": "MISS", "text": "❌", "x_px": actor_px[0], "y_px": actor_px[1]})
        elif ev.action_verb == "rebound":
            anns.append({"type": "REB", "text": "REB", "x_px": actor_px[0], "y_px": actor_px[1]})
        elif ev.action_verb == "foul":
            anns.append({"type": "PF", "text": "PF", "x_px": actor_px[0], "y_px": actor_px[1]})
        elif ev.action_verb == "turnover":
            anns.append({"type": "TOV", "text": "TOV", "x_px": actor_px[0], "y_px": actor_px[1]})
        elif ev.action_verb == "enters":
            anns.append({"type": "SUB", "text": "SUB", "x_px": actor_px[0], "y_px": actor_px[1]})
        annotation = anns

        # 篮球状态
        if is_shot_verb:
            ball = {"x_px": actor_px[0], "y_px": actor_px[1], "holder": None}
        elif actor:
            ball = {"x_px": actor_px[0], "y_px": actor_px[1], "holder": actor}
        # 无 actor 事件（period/timeout/jump ball）：篮球保持上一状态

        # 单调全局时间：统一每事件 DEFAULT_EVENT_S（架构 §9 允许「默认 2s」兜底）。
        # 不依赖真实 clock 差，保证时间线 bounded、deterministic、可观赏。
        # 注：animation.build_frames 对逐段帧数设上限（MAX_FRAMES_PER_SEGMENT /
        # TARGET_TOTAL_FRAMES），一场 ~600 事件实际仅生成 ≤ ~4000 帧（而非旧估算
        # 的 ~2.8 万帧），以保证回放响应 < 15MB、可前端加载。
        g_t = prev_t + DEFAULT_EVENT_S
        prev_t, prev_clock, prev_period = g_t, ev.clock_seconds, ev.period

        snapshot = {k: dict(v) for k, v in known.items()}
        resolved.append(ResolvedEvent(
            event_index=ev.event_index,
            game_id=ev.game_id,
            season=ev.season,
            period=ev.period,
            clock_seconds=ev.clock_seconds,
            event_type=ev.event_type,
            subtype=ev.subtype,
            action_verb=ev.action_verb,
            player=actor,
            team_abbr=team_abbr,
            x=ev.x, y=ev.y, dist=ev.dist,
            actor_px=actor_px,
            actor_pos_source=actor_pos_source,
            annotation=annotation,
            snapshot=snapshot,
            ball=dict(ball),
            global_t=g_t,
        ))
    return resolved


def build_frames_from_events(events: List[PbPEvent], fps: int = 30, full_court: bool = False) -> Dict[str, list]:
    """解析事件并生成逐帧序列（委托 animation）。

    返回 dict：``{"frames": [...], "events": [...]}``。
      - frames：逐帧坐标序列（与现有前端契约一致，坐标已为 SVG 像素）
      - events：PbPEvent 的精简投影，用于前端同步 PBP 文字解说（节次/时钟/比分）
        与 frames 同序、按 event_index 对应；轻量文本，不塞进每帧以控体积。
    """
    from backend.services.tactics_engine.animation import build_frames

    resolved = resolve_positions(events, full_court)
    frames = build_frames(resolved, fps)
    events_list = [{
        "event_index": ev.event_index,
        "period": ev.period,
        "clock_seconds": ev.clock_seconds,
        "description": ev.description,
        "team": ev.team,
        "action_verb": ev.action_verb,
        "player": ev.player,
        "player2": ev.player2,
        "h_pts": ev.h_pts,
        "a_pts": ev.a_pts,
    } for ev in events]
    return {"frames": frames, "events": events_list}


def build_frames(game_id: str, season, fps: int = 30, full_court: bool = False) -> Dict[str, list]:
    """便捷：按 game_id/season 直接生成逐帧序列。"""
    events = build_event_sequence(game_id, season)
    return build_frames_from_events(events, fps, full_court)
