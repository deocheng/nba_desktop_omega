"""NBACore v8 — /tactics router（Layer 3，纯编排）。

战术板 + PBP 动态回放 v1 薄编排路由。本路由**不含任何 SQL / 计算逻辑**
（v8 §2 Layer 3 强制）：仅做请求校验、调用 TacticsService 门面、塑形
``{code, data, message}`` 信封。所有坐标映射/插值/帧生成均在 Engine 层。

接口清单（architecture.md §5）：
    GET  /tactics/templates                  列出内置 ≥8 模板摘要
    GET  /tactics/templates/{id}             取单模板（formation+steps+帧+箭头）
    GET  /tactics/games?season=              该季可回放比赛（仅 br_crawler 有 xy）
    GET  /tactics/replay/metadata/{game_id}?season=  比赛元数据
    POST /tactics/replay                     生成逐帧坐标序列（核心）
    POST /tactics/ai/generate                 P2 预留：v1 返回 501（static 可用）
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.services.tactics_engine import schemas, service

router = APIRouter(prefix="/tactics", tags=["tactics"])

_svc = service.TacticsService()


@router.get("/templates")
def get_templates():
    """列出内置 ≥8 战术模板（id/name/description/meta，不含坐标）。"""
    try:
        return {"code": 0, "data": _svc.list_templates(), "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"list templates failed: {exc}")


@router.get("/templates/{template_id}")
def get_template(template_id: str, fps: int = Query(30, ge=1, le=60)):
    """取单模板完整数据 + 逐帧序列 + 预映射箭头（用于动画）。"""
    try:
        return {"code": 0, "data": _svc.render_template(template_id, fps), "message": "ok"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"render template failed: {exc}")


@router.get("/games")
def get_games(season: str = Query("2025", description="NBA season，如 2025")):
    """列出该赛季可回放比赛（含 br_crawler xy 的 gameid + 两队 + 事件数）。"""
    try:
        return {"code": 0, "data": _svc.list_games(season), "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"list games failed: {exc}")


@router.get("/replay/metadata/{game_id}")
def get_replay_metadata(game_id: str, season: str = Query("2025", description="NBA season")):
    """比赛元数据（队、节范围、时钟范围、事件数、xy 覆盖数）。"""
    try:
        meta = _svc.game_meta(game_id, season)
        if meta is None:
            raise HTTPException(
                status_code=404,
                detail=f"无回放元数据: game {game_id} season {season}",
            )
        return {"code": 0, "data": meta, "message": "ok"}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"replay metadata failed: {exc}")


@router.post("/replay")
def post_replay(req: schemas.ReplayRequest):
    """生成一场比赛的逐帧坐标序列（核心接口）。"""
    try:
        return {"code": 0, "data": _svc.replay(req), "message": "ok"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"replay failed: {exc}")


@router.post("/ai/generate")
def post_ai_generate(req: schemas.TacticGenerateRequest):
    """AI 战术生成（P2 预留）。

    - provider='static'：返回内置模板（v1 可用，保证接口可测可运行）。
    - provider='llm'：预留 LLM/Ollama 插槽，v1 尚未启用，返回 501。
    """
    try:
        if req.provider == "static":
            tpl = _svc.generate_tactic(req.prompt, "static")
            return {"code": 0, "data": tpl.model_dump(), "message": "ok"}
        # P2：真实 LLM 生成尚未启用
        raise HTTPException(
            status_code=501,
            detail="AI 战术生成（LLM/Ollama）尚未启用（P2 / Mac+Ollama 远期目标）",
        )
    except HTTPException:
        raise
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"ai generate failed: {exc}")
