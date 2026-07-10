"""NBACore v8 — Tactics Engine 内置战术模板库（T03，只读、硬编码）。

内置 ≥8 个标准 NBA 进攻战术模板（v1 只读，无写路径）：
    Pick-and-Roll / Horns / Motion Offense / Floppy / Spain PnR /
    Zone Buster / Fast Break / Isolation

每个模板：5 人半场初始站位（formation）+ 1–2 条移动路径（steps）。
坐标使用与 PBP 同源的 (x, y) 语义（x∈[-250,250]，y∈[0,470] 半场攻击区），
经 coords.map_xy_to_svg 渲染，保证模板与回放同一坐标系。

导出：
    list_templates()      → 模板摘要列表（id/name/description/meta，无坐标）
    get_template(id)      → 完整 TacticTemplate（含 formation+steps）
    all_templates()       → 内部全部模板（供 AI 生成器复用）
    resolve_ball_path(t)  → 解析篮球落点序列（源坐标）
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from backend.services.tactics_engine.schemas import PlayerSpot, TacticStep, TacticTemplate

# 进攻方统一用 'home'（蓝色）渲染；v1 模板演示聚焦进攻跑位。
_HOME = "home"


def _s(slot: int, label: str, x: float, y: float, team: str = _HOME) -> PlayerSpot:
    return PlayerSpot(slot=slot, label=label, team=team, x=float(x), y=float(y))


# ── 8 个内置模板 ──
_TEMPLATES: List[TacticTemplate] = [
    TacticTemplate(
        id="pick_and_roll",
        name="Pick-and-Roll",
        description="持球人借掩护摆脱后突破或分球，掩护者顺下/外弹。",
        formation=[
            _s(1, "1", 0, 400), _s(2, "2", 170, 250), _s(3, "3", -170, 250),
            _s(4, "4", -70, 180), _s(5, "5", 70, 200),
        ],
        ball_start=(0.0, 400.0),
        steps=[
            TacticStep(index=0, action="screen", actor_slot=5,
                       path=[(70, 200), (40, 360)], ball_to=1, duration_s=1.5),
            TacticStep(index=1, action="roll", actor_slot=5,
                       path=[(40, 360), (30, 120)], ball_to=5, duration_s=1.5),
        ],
        meta={"offense": "home", "tags": ["half-court", "pick-and-roll"]},
    ),
    TacticTemplate(
        id="horns",
        name="Horns",
        description="以 1-2-2（弧顶+双肘）为基础的灵活进攻，双肘大个给持球人双球掩护。",
        formation=[
            _s(1, "1", 0, 400), _s(2, "2", -220, 60), _s(3, "3", 220, 60),
            _s(4, "4", -80, 210), _s(5, "5", 80, 210),
        ],
        ball_start=(0.0, 400.0),
        steps=[
            TacticStep(index=0, action="screen", actor_slot=4,
                       path=[(-80, 210), (-30, 340)], ball_to=1, duration_s=1.4),
            TacticStep(index=1, action="pop", actor_slot=5,
                       path=[(80, 210), (120, 150)], ball_to=4, duration_s=1.6),
        ],
        meta={"offense": "home", "tags": ["half-court", "horns"]},
    ),
    TacticTemplate(
        id="motion_offense",
        name="Motion Offense",
        description="以空间/传球/连续切入为核心的阅读型进攻，无固定套路。",
        formation=[
            _s(1, "1", 0, 400), _s(2, "2", 170, 250), _s(3, "3", -170, 250),
            _s(4, "4", 0, 250), _s(5, "5", 60, 120),
        ],
        ball_start=(0.0, 400.0),
        steps=[
            TacticStep(index=0, action="cut", actor_slot=2,
                       path=[(170, 250), (60, 140)], ball_to=2, duration_s=1.8),
            TacticStep(index=1, action="dribble", actor_slot=1,
                       path=[(0, 400), (0, 300)], ball_to=1, duration_s=1.2),
        ],
        meta={"offense": "home", "tags": ["motion", "continuity"]},
    ),
    TacticTemplate(
        id="floppy",
        name="Floppy",
        description="射手从篮下借单侧/阶梯掩护切至外线接球投篮。",
        formation=[
            _s(1, "1", 0, 400), _s(2, "2", 200, 80), _s(3, "3", -170, 250),
            _s(4, "4", -60, 120), _s(5, "5", 80, 210),
        ],
        ball_start=(0.0, 400.0),
        steps=[
            TacticStep(index=0, action="screen", actor_slot=4,
                       path=[(-60, 120), (-40, 80)], ball_to=1, duration_s=1.2),
            TacticStep(index=1, action="cut", actor_slot=2,
                       path=[(200, 80), (-120, 230)], ball_to=2, duration_s=1.6),
        ],
        meta={"offense": "home", "tags": ["floppy", "off-ball"]},
    ),
    TacticTemplate(
        id="spain_pnr",
        name="Spain Pick-and-Roll",
        description="标准 PnR 基础上为顺下者加一道背掩护，专克 drop/hedge。",
        formation=[
            _s(1, "1", 0, 400), _s(2, "2", 180, 120), _s(3, "3", -170, 250),
            _s(4, "4", 220, 60), _s(5, "5", 50, 210),
        ],
        ball_start=(0.0, 400.0),
        steps=[
            TacticStep(index=0, action="screen", actor_slot=5,
                       path=[(50, 210), (30, 360)], ball_to=1, duration_s=1.4),
            TacticStep(index=1, action="screen", actor_slot=2,
                       path=[(180, 120), (60, 150)], ball_to=5, duration_s=1.6),
        ],
        meta={"offense": "home", "tags": ["spain", "pick-and-roll"]},
    ),
    TacticTemplate(
        id="zone_buster",
        name="Zone Buster (1-3-1)",
        description="以 1-3-1 落位嵌入空隙、用快速传导球调动 2-3 联防。",
        formation=[
            _s(1, "1", 0, 400), _s(2, "2", 170, 250), _s(3, "3", -170, 250),
            _s(4, "4", 0, 250), _s(5, "5", 210, 90),
        ],
        ball_start=(0.0, 400.0),
        steps=[
            TacticStep(index=0, action="pass", actor_slot=1,
                       path=[(0, 400), (0, 400)], ball_to=4, duration_s=1.0),
            TacticStep(index=1, action="cut", actor_slot=5,
                       path=[(210, 90), (120, 160)], ball_to=5, duration_s=1.4),
        ],
        meta={"offense": "home", "tags": ["zone", "1-3-1"]},
    ),
    TacticTemplate(
        id="fast_break",
        name="Fast Break",
        description="抢断/篮板后趁防守未落位迅速推进得分的提速进攻。",
        formation=[
            _s(1, "1", 0, 430), _s(2, "2", 150, 400), _s(3, "3", -150, 400),
            _s(4, "4", -80, 300), _s(5, "5", 0, 250),
        ],
        ball_start=(0.0, 430.0),
        steps=[
            TacticStep(index=0, action="dribble", actor_slot=1,
                       path=[(0, 430), (0, 250)], ball_to=1, duration_s=1.8),
            TacticStep(index=1, action="roll", actor_slot=5,
                       path=[(0, 250), (0, 120)], ball_to=5, duration_s=1.2),
        ],
        meta={"offense": "home", "tags": ["transition", "fast-break"]},
    ),
    TacticTemplate(
        id="isolation",
        name="Isolation (Iso)",
        description="清空一侧为持球得分手制造 1v1 空间的进攻布置。",
        formation=[
            _s(1, "1", 160, 250), _s(2, "2", -220, 70), _s(3, "3", 220, 70),
            _s(4, "4", -120, 200), _s(5, "5", 60, 120),
        ],
        ball_start=(160.0, 250.0),
        steps=[
            TacticStep(index=0, action="dribble", actor_slot=1,
                       path=[(160, 250), (120, 180)], ball_to=1, duration_s=1.5),
            TacticStep(index=1, action="dribble", actor_slot=1,
                       path=[(120, 180), (60, 140)], ball_to=1, duration_s=1.5),
        ],
        meta={"offense": "home", "tags": ["isolation", "1v1"]},
    ),
]


def list_templates() -> List[Dict]:
    """返回模板摘要列表（不含坐标）。"""
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "meta": t.meta,
        }
        for t in _TEMPLATES
    ]


def get_template(template_id: str) -> TacticTemplate:
    """按 id 取完整模板；不存在抛 KeyError。"""
    for t in _TEMPLATES:
        if t.id == template_id:
            return t
    raise KeyError(f"未知战术模板: {template_id}")


def all_templates() -> List[TacticTemplate]:
    """内部：返回全部模板（供 AI 生成器复用）。"""
    return list(_TEMPLATES)


def resolve_ball_path(tpl: TacticTemplate) -> List[Tuple[float, float]]:
    """解析篮球落点序列（源坐标）：ball_start + 每步目标点。"""
    positions: Dict[int, Tuple[float, float]] = {
        s.slot: (float(s.x), float(s.y)) for s in tpl.formation
    }
    path: List[Tuple[float, float]] = [
        (float(tpl.ball_start[0]), float(tpl.ball_start[1]))
    ]
    for step in tpl.steps:
        if step.ball_to is None:
            target = path[-1]
        elif isinstance(step.ball_to, int):
            target = positions.get(step.ball_to, path[-1])
        else:
            target = (float(step.ball_to[0]), float(step.ball_to[1]))
        path.append(target)
    return path
