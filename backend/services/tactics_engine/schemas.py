"""NBACore v8 — Tactics Engine 数据契约（Layer 2 内部 + API 共享）。

纯数据模型，无计算逻辑。定义：
    - 战术模板模型：PlayerSpot / TacticStep / TacticTemplate
    - 回放帧模型：ReplayFrame / PlayerSprite / BallSprite / Annotation
    - 请求 / 结果：ReplayRequest / ReplayResult / ReplayMeta
    - 引擎内部：PbPEvent / GameMeta
    - AI 生成请求：TacticGenerateRequest

坐标说明：所有 x/y 为源数据语义（x∈[-250,250]，y 为距底线距离，全场帧
y∈[-52,842]，约 94ft×10）。经 coords.map_xy_to_svg 折叠映射到半场 SVG
像素。帧 JSON 中的坐标均为已解析像素（x_px/y_px），前端不再做任何换算。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field


# ───────────────────────── 战术模板模型 ─────────────────────────
class PlayerSpot(BaseModel):
    """战术初始站位中的一名球员。"""

    slot: int = Field(..., description="出场 slot（1-5），作为圆圈号码")
    label: str = Field(..., description="圆圈显示：号码或姓名缩写")
    team: str = Field("home", description="'home' | 'away'")
    x: float = Field(..., description="源坐标系 x（与 PBP 同语义）")
    y: float = Field(..., description="源坐标系 y")


class TacticStep(BaseModel):
    """战术中的一个动作步骤（用于展开为逐帧路径）。"""

    index: int = Field(..., description="步骤序号，从 0 起")
    action: str = Field(..., description="screen/cut/pass/dribble/roll/pop")
    actor_slot: int = Field(..., description="执行该动作的球员 slot")
    path: List[Tuple[float, float]] = Field(
        default_factory=list, description="actor 移动路径点序列（源坐标）"
    )
    ball_to: Optional[Union[int, Tuple[float, float]]] = Field(
        default=None, description="球目标：目标 slot 或落点 (x,y)；None=保持"
    )
    duration_s: float = Field(2.0, description="该步骤时长（秒）")


class TacticTemplate(BaseModel):
    """一个内置战术模板（formation + steps + ball_path）。"""

    id: str
    name: str
    description: str = ""
    formation: List[PlayerSpot] = Field(default_factory=list)
    ball_start: Tuple[float, float] = Field(default=(0.0, 0.0))
    steps: List[TacticStep] = Field(default_factory=list)
    ball_path: List[Tuple[float, float]] = Field(default_factory=list)
    meta: Dict[str, object] = Field(default_factory=dict)

    def to_frames(self, fps: int = 30) -> List[dict]:
        """便捷入口：将模板展开为逐帧序列（实际计算在 animation 层）。"""
        from backend.services.tactics_engine.animation import build_frames_from_template

        return build_frames_from_template(self, fps)


# ───────────────────────── 回放帧模型 ─────────────────────────
class PlayerSprite(BaseModel):
    """帧中一名球员（坐标已是 SVG 像素）。"""

    player_id: str
    label: str
    team: str
    color: str
    x_px: float
    y_px: float
    pos_source: str = "real"  # real / last_known / default


class BallSprite(BaseModel):
    """帧中篮球（坐标已是 SVG 像素）。"""

    x_px: float
    y_px: float
    holder: Optional[str] = None  # player_id 或 None


class Annotation(BaseModel):
    """事件标注气泡。"""

    type: str  # MAKE / MISS / AST / REB / PF / SUB / TOV
    text: str
    x_px: float
    y_px: float


class ReplayFrame(BaseModel):
    """单帧（球员坐标帧 + 篮球坐标帧 + 事件标注）。"""

    t: float
    players: List[PlayerSprite] = Field(default_factory=list)
    ball: Optional[BallSprite] = None
    annotations: List[Annotation] = Field(default_factory=list)
    event_index: int = -1


# ───────────────────────── 请求 / 结果 ─────────────────────────
class ReplayRequest(BaseModel):
    """PBP 回放请求。"""

    game_id: str
    season: str
    period: Optional[int] = None
    start_clock: Optional[int] = None
    segment: Optional[str] = None
    speed: float = 1.0
    frame_rate: int = 30


class ReplayMeta(BaseModel):
    """回放元数据。"""

    fps: int = 30
    duration_s: float = 0.0
    frame_count: int = 0
    court: Dict[str, int] = Field(default_factory=dict)
    teams: Dict[str, str] = Field(default_factory=dict)
    period: Optional[int] = None
    clock: Tuple[float, float] = (0.0, 0.0)
    event_count: int = 0


class ReplayResult(BaseModel):
    """回放结果（帧序列 + 元数据）。"""

    game_id: str
    season: str
    frames: List[ReplayFrame] = Field(default_factory=list)
    meta: ReplayMeta


class TacticGenerateRequest(BaseModel):
    """AI 战术生成请求（P2 预留）。"""

    prompt: str = ""
    provider: str = "static"  # static | llm


# ───────────────────────── 引擎内部 ─────────────────────────
class PbPEvent(BaseModel):
    """一条 PBP 事件（已序列化的内部模型）。"""

    event_index: int
    game_id: str
    season: str
    period: int
    clock_seconds: float
    event_type: str = ""
    subtype: str = ""
    action_verb: str = ""
    player: str = ""
    player2: str = ""
    team: str = ""
    x: int = 0
    y: int = 0
    dist: int = 0


class GameMeta(BaseModel):
    """单场比赛元数据。"""

    game_id: str
    season: str
    teams: List[str] = Field(default_factory=list)
    period_min: int = 0
    period_max: int = 0
    event_count: int = 0
    xy_count: int = 0


# ───────────────────────── 共享常量 ─────────────────────────
ANNOTATION_TYPES = ("MAKE", "MISS", "AST", "REB", "PF", "SUB", "TOV")
