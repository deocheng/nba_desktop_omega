"""NBACore v8 — Tactics Engine 门面（Facade，供 API Layer 3 编排，T07）。

汇总 engine 能力：
    replay(game_id, season, fps)        → PBP 逐帧序列（ReplayResult 形态 dict）
    list_templates()                    → 内置模板摘要列表
    get_template(id) / render_template(id, fps) → 模板数据 + 逐帧序列 + 预映射箭头
    generate_tactic(prompt, provider)   → AI 生成（P2 预留）
    list_games(season) / game_meta(...)  → 只读 PBP 元数据

本类仅做编排 + 结果塑形，不含坐标/插值数学（在 coords/animation/replay_engine）。
所有帧坐标已在 Engine 层生成，前端零计算。
"""
from __future__ import annotations

from typing import Dict, List, Optional

# 回放有效帧率上限：配合 animation.MAX_FRAMES_PER_SEGMENT / TARGET_TOTAL_FRAMES
# 的逐段帧数上限，保证响应体 < 15MB 且播放时长落在 2~4 分钟区间。
# 前端 rAF 按 meta.fps 推进，故 meta.fps 必须等于实际生成帧率（此处 clamp 后的值）。
# 说明：帧数由 seg_cap 主导，降低 fps 不会增加帧数，只把播放速度调到更舒适的档位。
REPLAY_FPS_CAP: int = 20

from backend.services.tactics_engine import (
    ai_generator,
    animation,
    coords,
    db,
    replay_engine,
    schemas,
    tactic_templates,
)


class TacticsService:
    """战术板引擎门面。"""

    def __init__(self) -> None:
        self._ai = ai_generator

    # ───────────────────────── PBP 动态回放 ─────────────────────────
    def replay(self, req: schemas.ReplayRequest) -> Dict:
        """生成一场比赛的逐帧坐标序列（核心）。

        有效帧率 clamp 到 REPLAY_FPS_CAP，配合 animation 的逐段帧数上限，
        把响应体压到 < 15MB 且播放时长落在 2~4 分钟；meta.fps 与实际生成帧率一致。
        """
        events = replay_engine.build_event_sequence(req.game_id, req.season)
        if not events:
            raise LookupError(f"无回放数据: game {req.game_id} season {req.season}")
        fps = max(1, min(int(req.frame_rate or 30), REPLAY_FPS_CAP))
        # 回放恒走全场（full_court=True）：双篮筐广播视角 + 同步 PBP 文字解说。
        res = replay_engine.build_frames_from_events(events, fps, full_court=True)
        meta = self._build_meta(req, res["frames"], events, fps, full_court=True)
        return {
            "game_id": req.game_id,
            "season": str(req.season),
            "frames": res["frames"],
            "events": res["events"],
            "meta": meta,
        }

    def _build_meta(self, req, frames: List[dict], events, fps: int, full_court: bool = False) -> Dict:
        gmeta = db.load_game_meta(req.game_id, req.season)
        teams: Dict[str, str] = {}
        if gmeta and gmeta.teams:
            teams = {
                "home": gmeta.teams[0],
                "away": gmeta.teams[1] if len(gmeta.teams) > 1 else "",
            }
        first_clock = events[0].clock_seconds if events else 0.0
        last_clock = events[-1].clock_seconds if events else 0.0
        # 全场回放：court 写 mode='full' + 全场尺寸；战术板模板仍为半场（见 render_template）
        court = (
            {"mode": "full", "w": coords.FULL_SVG_W, "h": coords.FULL_SVG_H}
            if full_court
            else {"w": coords.SVG_W, "h": coords.SVG_H}
        )
        return {
            "fps": fps,
            "duration_s": round(frames[-1]["t"], 2) if frames else 0.0,
            "frame_count": len(frames),
            "court": court,
            "teams": teams,
            "period": events[0].period if events else None,
            "clock": [first_clock, last_clock],
            "event_count": len(events),
        }

    # ───────────────────────── 模板库 ─────────────────────────
    def list_templates(self) -> List[Dict]:
        return tactic_templates.list_templates()

    def get_template(self, template_id: str) -> schemas.TacticTemplate:
        return tactic_templates.get_template(template_id)

    def render_template(self, template_id: str, fps: int = 30) -> Dict:
        """返回模板完整数据 + 逐帧序列 + 预映射箭头，供前端演示。"""
        tpl = tactic_templates.get_template(template_id)
        frames = animation.build_frames_from_template(tpl, fps)
        # 预映射：球员路径箭头 + 篮球路径（前端零坐标计算）
        arrows_svg = [
            [list(coords.map_xy_to_svg(*p)) for p in step.path]
            for step in tpl.steps
        ]
        ball_path = tactic_templates.resolve_ball_path(tpl)
        ball_path_svg = [list(coords.map_xy_to_svg(*p)) for p in ball_path]
        return {
            "template": tpl.model_dump(),
            "frames": frames,
            "arrows_svg": arrows_svg,
            "ball_path_svg": ball_path_svg,
            "meta": {
                "fps": fps,
                "duration_s": round(frames[-1]["t"], 2) if frames else 0.0,
                "frame_count": len(frames),
                "court": {"w": coords.SVG_W, "h": coords.SVG_H},
                "teams": {"home": "HOME", "away": "AWAY"},
                "template_id": tpl.id,
            },
        }

    # ───────────────────────── 只读 PBP 元数据 ─────────────────────────
    def list_games(self, season) -> List[Dict]:
        return db.list_replay_games(season)

    def game_meta(self, game_id: str, season) -> Optional[Dict]:
        g = db.load_game_meta(game_id, season)
        return g.model_dump() if g is not None else None

    # ───────────────────────── AI 生成（P2 预留）─────────────────────────
    def generate_tactic(self, prompt: str, provider: str = "static") -> schemas.TacticTemplate:
        gen = ai_generator.get_generator(provider)
        return gen.generate_from_natural_language(prompt, {})
