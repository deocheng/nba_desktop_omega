"""NBACore v8 — /trade router (Layer 3, pure orchestration).

交易模拟器 v1 薄编排路由（TRADE-01/02/03/05/07/08/09/10）。本路由**不含任何
SQL / pandas / 计算逻辑**（v8 §2 Layer 3 强制）：仅做请求校验、调用
``TradeService`` 门面、塑形 ``{code, data, message}`` 信封。

接口清单（architecture.md §六）：
    POST /trade/validate                  多队交易合法性校验
    POST /trade/suggest                  薪资匹配建议
    POST /trade/generate                 交易方案生成
    GET  /trade/timeline/player/{id}     球员 6 季时间线
    GET  /trade/timeline/team/{abbr}     球队 6 季时间线
    GET  /trade/rules/{season}           读取规则常量
    PUT  /trade/rules/{season}           受控更新规则常量
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.services.trade_engine import schemas, service

router = APIRouter(prefix="/trade", tags=["trade"])

_svc = service.TradeService()


@router.post("/validate")
def post_validate(req: schemas.TradeValidateRequest):
    """多队交易合法性校验（TRADE-01）。"""
    try:
        return {"code": 0, "data": _svc.validate(req), "message": "ok"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"trade validate failed: {exc}")


@router.post("/suggest")
def post_suggest(req: schemas.TradeSuggestRequest):
    """薪资匹配建议（TRADE-02）。"""
    try:
        return {"code": 0, "data": _svc.suggest(req), "message": "ok"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"trade suggest failed: {exc}")


@router.post("/generate")
def post_generate(req: schemas.TradeGenerateRequest):
    """交易方案生成（TRADE-07）。"""
    try:
        return {"code": 0, "data": _svc.generate(req), "message": "ok"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"trade generate failed: {exc}")


@router.get("/timeline/player/{player_id}")
def get_player_timeline(player_id: str, season: str = Query("2025-26")):
    """球员 6 季薪资时间线（TRADE-08）。"""
    try:
        data = _svc.player_timeline(player_id, season)
        if data is None:
            raise HTTPException(status_code=404, detail=f"player {player_id} not found")
        return {"code": 0, "data": data, "message": "ok"}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"player timeline failed: {exc}")


@router.get("/timeline/team/{team_abbr}")
def get_team_timeline(team_abbr: str, season: str = Query("2025-26")):
    """球队 6 季薪资时间线（TRADE-09）。"""
    try:
        data = _svc.team_timeline(team_abbr, season)
        if data is None:
            raise HTTPException(status_code=404, detail=f"team {team_abbr} not found")
        return {"code": 0, "data": data, "message": "ok"}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"team timeline failed: {exc}")


@router.get("/rules/{season}")
def get_rules(season: str, league: str = Query("NBA")):
    """读取联盟薪资规则常量（TRADE-05）。"""
    try:
        data = _svc.get_rules(season, league)
        if data is None:
            raise HTTPException(status_code=404, detail=f"rules {league}/{season} not found")
        return {"code": 0, "data": data, "message": "ok"}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"get rules failed: {exc}")


@router.put("/rules/{season}")
def put_rules(season: str, req: schemas.RulesUpsertRequest):
    """受控更新联盟薪资规则常量（TRADE-10 / T11，专用写池 + 参数化 SQL）。"""
    req.season = season  # 以路径参数为准
    try:
        return {"code": 0, "data": _svc.upsert_rules(req), "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"upsert rules failed: {exc}")


@router.get("/players/{team_abbr}")
def get_team_players(team_abbr: str, season: str = Query("2025-26")):
    """列出某队球员（轻量视图，供前端构建器下拉，纯读编排）。"""
    try:
        data = _svc.list_players(team_abbr, season)
        return {"code": 0, "data": data, "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"list players failed: {exc}")
