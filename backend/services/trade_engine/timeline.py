"""NBACore v8 — Timeline Service (T08 / TRADE-08 & TRADE-09).

- ``player_timeline``：单球员 6 季薪资 / 保障 / 选项 时间线。
- ``team_timeline``：球队 6 季总薪资 / 保障总额 / 税档态势 时间线。

数据源：player_contracts（球员）/ team_payroll（球队）+ league_salary_rules（税档）。
税档状态逐季分类（v1 仅 2025-26 有规则常量，未来季沿用当前阈值，已在 PRD 标注）。
"""
from __future__ import annotations

from typing import Optional

from backend.services.trade_engine import db, match_engine, schemas


class TimelineService:
    """球员 / 球队薪资时间线（纯读，经 db 层）。"""

    def player_timeline(
        self, player_id: str, season: str
    ) -> Optional[schemas.PlayerTimeline]:
        """单球员 6 季薪资时间线（TRADE-08）。"""
        assets = db.load_players_by_ids([player_id], season)
        if player_id not in assets:
            return None
        a = assets[player_id]
        return schemas.PlayerTimeline(
            player_id=a.player_id,
            player_name=a.player_name,
            team_abbr=a.team_abbr,
            season=season,
            salaries=a.salary_by_season,
            guaranteed=a.guaranteed_by_season,
            opts=a.opt_by_season,
            is_two_way=a.is_two_way,
            is_partial=a.is_partial,
        )

    def team_timeline(
        self, team_abbr: str, season: str
    ) -> Optional[schemas.TeamTimeline]:
        """球队 6 季薪资 / 税档时间线（TRADE-09）。"""
        payrolls = db.load_team_payrolls([team_abbr], season)
        if team_abbr not in payrolls:
            return None
        p = payrolls[team_abbr]
        rules = db.load_rules(season) or schemas.LeagueSalaryRules(season=season)

        totals = p.get("totals", {})
        total_guaranteed = p.get("total_guaranteed", 0)
        tax_status: dict = {}
        apron_status: dict = {}
        # 逐季分类（v1 统一用当前 season 规则常量）
        for s in _season_list():
            sal = totals.get(s, 0)
            tax_status[s] = match_engine.tax_status_of(sal, rules)
            apron_status[s] = match_engine.apron_status_of(sal, rules)

        return schemas.TeamTimeline(
            team_abbr=team_abbr,
            team_name=p.get("team_name", team_abbr),
            season=season,
            total_salary=totals,
            total_guaranteed={s: total_guaranteed for s in _season_list()},
            tax_status=tax_status,
            apron_status=apron_status,
        )


def _season_list():
    from backend.services.trade_engine import constants

    return constants.all_seasons()
