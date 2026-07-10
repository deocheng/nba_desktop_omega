"""NBACore v8.3.1 — /api/workspaces CRUD router (pure orchestration, Layer 3).

Maps HTTP to the Workspace Engine manager. No pandas / SQL / compute logic
here (v8 §2 Layer 3 mandate). All persistence is fenced inside the engine's
dedicated write-path Data Layer.
"""
from __future__ import annotations

import io
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api.schemas import (
    FormulaPreset,
    WorkspaceChartCreate,
    WorkspaceChartResponse,
    WorkspaceCreate,
    WorkspaceDatasetLink,
    WorkspaceFormulaLink,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from backend.services.workspace_engine import (
    WorkspaceValidationError,
    add_chart,
    add_dataset,
    add_formula,
    create,
    delete,
    duplicate,
    get_chart,
    list_workspaces,
    load,
    remove_chart,
    remove_dataset,
    remove_formula,
    update_chart,
    update_workspace,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspace"])


def _not_found(workspace_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")


# ── Workspace lifecycle ──

@router.post("", response_model=WorkspaceResponse, status_code=201)
def create_workspace(payload: WorkspaceCreate):
    try:
        ws = create(payload.name, payload.owner_id, payload.description, payload.status)
    except WorkspaceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return WorkspaceResponse(**ws.to_dict())


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces_endpoint(
    owner_id: int | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    wss = list_workspaces(owner_id=owner_id, status=status, limit=limit, offset=offset)
    return [WorkspaceResponse(**w.to_dict()) for w in wss]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(workspace_id: int):
    ws = load(workspace_id)
    if ws is None:
        raise _not_found(workspace_id)
    return WorkspaceResponse(**ws.to_dict())


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace_endpoint(workspace_id: int, payload: WorkspaceUpdate):
    try:
        ws = update_workspace(
            workspace_id, name=payload.name, description=payload.description, status=payload.status
        )
    except WorkspaceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if ws is None:
        raise _not_found(workspace_id)
    return WorkspaceResponse(**ws.to_dict())


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace_endpoint(workspace_id: int):
    if not delete(workspace_id):
        raise _not_found(workspace_id)
    return None


@router.post("/{workspace_id}/duplicate", response_model=WorkspaceResponse, status_code=201)
def duplicate_workspace_endpoint(workspace_id: int, new_name: str | None = Query(None)):
    try:
        ws = duplicate(workspace_id, new_name)
    except ValueError as exc:
        raise _not_found(workspace_id) if "not found" in str(exc) else HTTPException(
            status_code=400, detail=str(exc)
        )
    return WorkspaceResponse(**ws.to_dict())


# ── Dataset links ──

@router.post("/{workspace_id}/datasets", response_model=WorkspaceResponse)
def link_dataset(workspace_id: int, link: WorkspaceDatasetLink):
    ws = add_dataset(workspace_id, link.dataset_id)
    if ws is None:
        raise _not_found(workspace_id)
    return WorkspaceResponse(**ws.to_dict())


@router.delete("/{workspace_id}/datasets/{dataset_id}", status_code=204)
def unlink_dataset(workspace_id: int, dataset_id: int):
    if not remove_dataset(workspace_id, dataset_id):
        raise _not_found(workspace_id)
    return None


# ── Formula links ──

@router.post("/{workspace_id}/formulas", response_model=WorkspaceResponse)
def link_formula(workspace_id: int, link: WorkspaceFormulaLink):
    ws = add_formula(workspace_id, link.formula_id)
    if ws is None:
        raise _not_found(workspace_id)
    return WorkspaceResponse(**ws.to_dict())


@router.delete("/{workspace_id}/formulas/{formula_id}", status_code=204)
def unlink_formula(workspace_id: int, formula_id: int):
    if not remove_formula(workspace_id, formula_id):
        raise _not_found(workspace_id)
    return None


# ── Charts ──

@router.post("/{workspace_id}/charts", response_model=WorkspaceChartResponse, status_code=201)
def create_chart(workspace_id: int, payload: WorkspaceChartCreate):
    if load(workspace_id) is None:
        raise _not_found(workspace_id)
    chart_id = add_chart(workspace_id, payload.name, payload.chart_config)
    chart = get_chart(chart_id)
    return WorkspaceChartResponse(**chart)


@router.put("/{workspace_id}/charts/{chart_id}", response_model=WorkspaceChartResponse)
def update_chart_endpoint(workspace_id: int, chart_id: int, payload: WorkspaceChartCreate):
    updated = update_chart(chart_id, name=payload.name, chart_config=payload.chart_config)
    if updated is None:
        raise _not_found(workspace_id)
    return WorkspaceChartResponse(**updated)


@router.delete("/{workspace_id}/charts/{chart_id}", status_code=204)
def delete_chart_endpoint(workspace_id: int, chart_id: int):
    if not remove_chart(chart_id):
        raise _not_found(workspace_id)
    return None


# ── Export (.nbacore) ──

@router.get("/{workspace_id}/export")
def export_workspace(workspace_id: int):
    ws = load(workspace_id)
    if ws is None:
        raise _not_found(workspace_id)
    data = json.dumps(ws.to_dict(), ensure_ascii=False, indent=2)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in ws.name)
    return StreamingResponse(
        io.StringIO(data),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.nbacore"'},
    )


# ── Formula Presets ──

_PRESET_FORMULAS: list[dict] = [
    # ── 效率类 ──
    {"id": 1, "name": "EFF", "category": "效率",
     "description": "效率值 — 衡量球员综合贡献 (PTS+REB+AST+STL+BLK) − (FGA−FGM)−(FTA−FTM)−TOV",
     "expression": "(PTS + REB + AST + STL + BLK) - (FGA - FGM) - (FTA - FTM) - TOV"},
    {"id": 2, "name": "TS%", "category": "命中率",
     "description": "真实命中率 — 考虑两分/三分/罚球的综合投篮效率 PTS / (2 × (FGA + 0.44 × FTA))",
     "expression": "PTS / (2 * (FGA + 0.44 * FTA))"},
    {"id": 3, "name": "PER", "category": "效率",
     "description": "球员效率评级（简化版）— 每分钟产出综合评分",
     "expression": "(PTS + REB + AST + STL + BLK - (FGA - FGM) - (FTA - FTM) - TOV) / MIN"},
    {"id": 4, "name": "PIE", "category": "影响力",
     "description": "球员影响力估算 — (PTS+FGM+FTM+REB+AST+STL+BLK−FGA−FTA−TOV) / (球队总和)",
     "expression": "(PTS + FGM + FTM + REB + AST + STL + BLK - FGA - FTA - TOV) / (TEAM_PTS + TEAM_FGM + TEAM_FTM + TEAM_REB + TEAM_AST + TEAM_STL + TEAM_BLK - TEAM_FGA - TEAM_FTA - TEAM_TOV)"},
    {"id": 5, "name": "ORTG", "category": "效率",
     "description": "进攻效率 — 每100回合得分 (PTS / POSS) × 100",
     "expression": "(PTS / POSS) * 100"},
    {"id": 6, "name": "DRTG", "category": "效率",
     "description": "防守效率 — 每100回合失分 对手得分相同的逻辑",
     "expression": "(OPP_PTS / OPP_POSS) * 100"},
    {"id": 7, "name": "净效率", "category": "综合",
     "description": "净效率值 = 进攻效率 − 防守效率",
     "expression": "ORTG - DRTG"},
    {"id": 11, "name": "USG%", "category": "效率",
     "description": "使用率 — 球员在场时使用的球队回合比例 (FGA + 0.44×FTA + TOV) / (球队FGA + 0.44×球队FTA + 球队TOV)",
     "expression": "(FGA + 0.44 * FTA + TOV) / (TEAM_FGA + 0.44 * TEAM_FTA + TEAM_TOV)"},
    {"id": 12, "name": "每回合得分", "category": "效率",
     "description": "每回合得分 PPP — 球员每次出手+失误平均产生的得分 PTS / (FGA + 0.44×FTA + TOV)",
     "expression": "PTS / (FGA + 0.44 * FTA + TOV)"},
    {"id": 13, "name": "比赛贡献值", "category": "效率",
     "description": "比赛贡献值 GmSc — (得分 + 0.4×命中数 − 0.7×出手数 − 0.4×(罚球出手−罚球命中) + 0.7×进攻篮板 + 0.3×防守篮板 + 抢断 + 0.7×助攻 + 0.7×盖帽 − 0.4×犯规 − 失误)",
     "expression": "PTS + 0.4*FGM - 0.7*FGA - 0.4*(FTA - FTM) + 0.7*ORB + 0.3*DRB + STL + 0.7*AST + 0.7*BLK - 0.4*PF - TOV"},
    {"id": 14, "name": "得分效率", "category": "效率",
     "description": "每次出手得分 PPS — 球员平均每次出手能得到多少分 PTS / FGA",
     "expression": "PTS / FGA"},

    # ── 命中率类 ──
    {"id": 8, "name": "三分占比", "category": "命中率",
     "description": "三分球出手占全部出手的比例 3PA / FGA",
     "expression": "FG3A / FGA"},
    {"id": 15, "name": "eFG%", "category": "命中率",
     "description": "有效命中率 — 考虑三分球价值的命中率 (FGM + 0.5×3PM) / FGA",
     "expression": "(FGM + 0.5 * FG3M) / FGA"},
    {"id": 16, "name": "罚球率", "category": "命中率",
     "description": "罚球率 FTr — 罚球出手数占投篮出手数的比例 FTA / FGA",
     "expression": "FTA / FGA"},
    {"id": 17, "name": "三分命中率", "category": "命中率",
     "description": "三分球命中率 3P% — 三分球命中数 / 三分球出手数",
     "expression": "FG3M / FG3A"},
    {"id": 18, "name": "两分命中率", "category": "命中率",
     "description": "两分球命中率 2P% — 两分球命中数 / 两分球出手数",
     "expression": "(FGM - FG3M) / (FGA - FG3A)"},
    {"id": 19, "name": "真实出手数", "category": "命中率",
     "description": "真实投篮出手数 TSA — FGA + 0.44 × FTA",
     "expression": "FGA + 0.44 * FTA"},
    {"id": 20, "name": "出手距离变化率", "category": "命中率",
     "description": "平均出手距离与联盟均值的偏差 — 衡量球员投篮分布的远近倾向",
     "expression": "AVG_DIST - 12"},

    # ── 篮板类 ──
    {"id": 10, "name": "篮板率", "category": "篮板",
     "description": "篮板率 TRB% — 球员在场时抢到的篮板占总篮板的比例 (REB × 球队总回合) / (MIN × (球队篮板 + 对手篮板))",
     "expression": "REB / TEAM_REB"},
    {"id": 21, "name": "进攻篮板率", "category": "篮板",
     "description": "进攻篮板率 ORB% — 球员在场时抢到的进攻篮板占总进攻篮板的比例 ORB / TEAM_ORB",
     "expression": "ORB / TEAM_ORB"},
    {"id": 22, "name": "防守篮板率", "category": "篮板",
     "description": "防守篮板率 DRB% — 球员在场时抢到的防守篮板占总防守篮板的比例 DRB / TEAM_DRB",
     "expression": "DRB / TEAM_DRB"},
    {"id": 23, "name": "进攻篮板占比", "category": "篮板",
     "description": "进攻篮板占个人总篮板的比例 ORB / REB",
     "expression": "ORB / REB"},
    {"id": 24, "name": "防守篮板占比", "category": "篮板",
     "description": "防守篮板占个人总篮板的比例 DRB / REB",
     "expression": "DRB / REB"},

    # ── 组织类 ──
    {"id": 9, "name": "助攻失误比", "category": "组织",
     "description": "助攻失误比 A/TO — 助攻数与失误数的比率",
     "expression": "AST / TOV"},
    {"id": 25, "name": "助攻率", "category": "组织",
     "description": "助攻率 AST% — 球员在场时队友进球中由他助攻的比例 AST / (TEAM_FGM - FGM)",
     "expression": "AST / (TEAM_FGM - FGM)"},
    {"id": 26, "name": "失误率", "category": "组织",
     "description": "失误率 TOV% — 每100回合失误次数 (TOV × 100) / (FGA + 0.44×FTA + TOV)",
     "expression": "TOV / (FGA + 0.44 * FTA + TOV)"},
    {"id": 27, "name": "助攻占比", "category": "组织",
     "description": "助攻占球队总助攻的比例 AST / TEAM_AST",
     "expression": "AST / TEAM_AST"},
    {"id": 28, "name": "每36分钟助攻", "category": "组织",
     "description": "每36分钟助攻数 — 将助攻数据标准化到36分钟出场时间 (AST / MIN) × 36",
     "expression": "(AST / MIN) * 36"},
    {"id": 29, "name": "得分助攻比", "category": "组织",
     "description": "得分与助攻的比率 PTS / AST — 衡量球员是得分型还是组织型",
     "expression": "PTS / AST"},

    # ── 防守类 ──
    {"id": 30, "name": "抢断率", "category": "防守",
     "description": "抢断率 STL% — 球员在场时每100回合抢断次数 (STL × 100) / 对手回合数",
     "expression": "STL / OPP_POSS * 100"},
    {"id": 31, "name": "盖帽率", "category": "防守",
     "description": "盖帽率 BLK% — 球员在场时每100回合盖帽次数 (BLK × 100) / 对手两分出手数",
     "expression": "BLK / OPP_FG2A * 100"},
    {"id": 32, "name": "防守贡献值", "category": "防守",
     "description": "防守贡献值 — 抢断 + 盖帽 + 防守篮板 + 0.5×犯规（简化版）",
     "expression": "STL + BLK + DRB + 0.5 * PF"},
    {"id": 33, "name": "抢断盖帽比", "category": "防守",
     "description": "抢断与盖帽的比率 STL / BLK — 衡量防守类型（外线/内线）",
     "expression": "STL / BLK"},
    {"id": 34, "name": "每36分钟抢断", "category": "防守",
     "description": "每36分钟抢断数 (STL / MIN) × 36",
     "expression": "(STL / MIN) * 36"},
    {"id": 35, "name": "每36分钟盖帽", "category": "防守",
     "description": "每36分钟盖帽数 (BLK / MIN) × 36",
     "expression": "(BLK / MIN) * 36"},
    {"id": 36, "name": "犯规率", "category": "防守",
     "description": "每36分钟犯规数 (PF / MIN) × 36",
     "expression": "(PF / MIN) * 36"},

    # ── 进阶类 ──
    {"id": 37, "name": "WS/48", "category": "进阶",
     "description": "每48分钟胜利贡献值 — 衡量球员每48分钟能为球队贡献多少胜利",
     "expression": "(WS / MIN) * 48"},
    {"id": 38, "name": "VORP", "category": "进阶",
     "description": "球员价值可替代性 — 球员相比同位置替代球员的价值增量",
     "expression": "VORP"},
    {"id": 39, "name": "BPM", "category": "进阶",
     "description": "正负值（框算版）— 基于基础数据估算的每百回合净胜分贡献",
     "expression": "BPM"},
    {"id": 40, "name": "OBPM", "category": "进阶",
     "description": "进攻正负值 — 基于基础数据估算的每百回合进攻端净胜分贡献",
     "expression": "OBPM"},
    {"id": 41, "name": "DBPM", "category": "进阶",
     "description": "防守正负值 — 基于基础数据估算的每百回合防守端净胜分贡献",
     "expression": "DBPM"},
    {"id": 42, "name": "使用率效率积", "category": "进阶",
     "description": "USG% × TS% — 综合衡量球权使用率和得分效率，高值代表高效的大核心",
     "expression": "USG_PCT * TS_PCT"},
    {"id": 43, "name": "真实正负效率", "category": "进阶",
     "description": "PER × (1 - 失误率) — 扣除失误成本后的效率值",
     "expression": "PER * (1 - TOV_PCT)"},

    # ── 每36分钟标准化 ──
    {"id": 44, "name": "每36分钟得分", "category": "标准化",
     "description": "每36分钟得分 — 将得分标准化到36分钟出场时间 (PTS / MIN) × 36",
     "expression": "(PTS / MIN) * 36"},
    {"id": 45, "name": "每36分钟篮板", "category": "标准化",
     "description": "每36分钟篮板 — 将篮板标准化到36分钟出场时间 (REB / MIN) × 36",
     "expression": "(REB / MIN) * 36"},
    {"id": 46, "name": "每36分钟进攻篮板", "category": "标准化",
     "description": "每36分钟进攻篮板 (ORB / MIN) × 36",
     "expression": "(ORB / MIN) * 36"},
    {"id": 47, "name": "每36分钟防守篮板", "category": "标准化",
     "description": "每36分钟防守篮板 (DRB / MIN) × 36",
     "expression": "(DRB / MIN) * 36"},
    {"id": 48, "name": "每36分钟抢断盖帽", "category": "标准化",
     "description": "每36分钟抢断+盖帽 (STL + BLK) / MIN × 36 — 衡量防守活跃度",
     "expression": "((STL + BLK) / MIN) * 36"},
    {"id": 49, "name": "每36分钟失误", "category": "标准化",
     "description": "每36分钟失误数 (TOV / MIN) × 36",
     "expression": "(TOV / MIN) * 36"},
    {"id": 50, "name": "每36分钟EFF", "category": "标准化",
     "description": "每36分钟效率值 (EFF / MIN) × 36 — 将EFF标准化到36分钟",
     "expression": "((PTS + REB + AST + STL + BLK - (FGA - FGM) - (FTA - FTM) - TOV) / MIN) * 36"},

    # ── 综合类 ──
    {"id": 51, "name": "两双概率", "category": "综合",
     "description": "达到两双的概率估算 — 基于得分+篮板+助攻中两项上双的综合指标",
     "expression": "(PTS >= 10 ? 1 : 0) + (REB >= 10 ? 1 : 0) + (AST >= 10 ? 1 : 0)"},
    {"id": 52, "name": "全面性指数", "category": "综合",
     "description": "全面性指数 — 得分+篮板+助攻+抢断+盖帽五项数据的均衡度",
     "expression": "PTS * 1 + REB * 1.2 + AST * 1.5 + STL * 2 + BLK * 2"},
    {"id": 53, "name": "得分爆发力", "category": "综合",
     "description": "得分爆发力 — 场均得分 × 真实命中率 × 使用率",
     "expression": "PTS_PG * TS_PCT * USG_PCT"},
    {"id": 54, "name": "防守积极度", "category": "综合",
     "description": "防守积极度 — (抢断 + 盖帽 + 防守篮板) / 出场时间 × 100",
     "expression": "((STL + BLK + DRB) / MIN) * 100"},
    {"id": 55, "name": "持球权重", "category": "综合",
     "description": "持球权重 — (助攻 + 失误 + 罚球出手×0.44 + 得分×0.5) / 球队回合数",
     "expression": "(AST + TOV + 0.44 * FTA + 0.5 * PTS) / TEAM_POSS"},
]



@router.get("/formulas/presets", response_model=list[FormulaPreset])
def list_formula_presets() -> list[FormulaPreset]:
    """List all preset NBA formulas available for import."""
    return [FormulaPreset(**f) for f in _PRESET_FORMULAS]
