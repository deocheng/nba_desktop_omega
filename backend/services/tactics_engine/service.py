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
        """生成一场比赛的逐帧坐标序列（核心）。"""
        events = replay_engine.build_event_sequence(req.game_id, req.season)
        if not events:
            raise LookupError(f"无回放数据: game {req.game_id} season {req.season}")
        frames = replay_engine.build_frames_from_events(events, req.frame_rate)
        meta = self._build_meta(req, frames, events)
        return {
            "game_id": req.game_id,
            "season": str(req.season),
            "frames": frames,
            "meta": meta,
        }

    def _build_meta(self, req, frames: List[dict], events) -> Dict:
        gmeta = db.load_game_meta(req.game_id, req.season)
        teams: Dict[str, str] = {}
        if gmeta and gmeta.teams:
            teams = {
                "home": gmeta.teams[0],
                "away": gmeta.teams[1] if len(gmeta.teams) > 1 else "",
            }
        first_clock = events[0].clock_seconds if events else 0.0
        last_clock = events[-1].clock_seconds if events else 0.0
        return {
            "fps": req.frame_rate,
            "duration_s": round(frames[-1]["t"], 2) if frames else 0.0,
            "frame_count": len(frames),
            "court": {"w": coords.SVG_W, "h": coords.SVG_H},
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
