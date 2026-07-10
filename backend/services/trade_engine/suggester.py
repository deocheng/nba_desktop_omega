"""NBACore v8 — Trade Suggester & Proposal Generator (T05 / T07).

- ``MatchSuggester``（TRADE-02）：对不通过的单队，自动给出「加/减球员」最小改动
  建议使其薪资匹配通过（仅同队可交易球员池）。
- ``ProposalGenerator``（TRADE-07）：给定目标球员 + 发起队，搜索可行的交易搭档
  与匹配方案（受默认深度上限约束：每队 ≤2 搭档、候选 Top-20、最大分支 K=200）。

全部计算在 Engine 层；建议/方案的合法性由 validate_leg（复用 NBA 规则）判定。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from backend.services.trade_engine import constants, db, schemas
from backend.services.trade_engine.rules import SalaryRuleSet
from backend.services.trade_engine.trade_graph import validate_leg


class MatchSuggester:
    """薪资匹配建议（TRADE-02）。"""

    def suggest(
        self,
        leg: schemas.TeamTradeLeg,
        rs: SalaryRuleSet,
        pool: List[schemas.PlayerAsset],
        rules: schemas.LeagueSalaryRules,
        as_of: datetime,
    ) -> List[schemas.Suggestion]:
        """返回使该队匹配通过的建议列表（增/减球员两种杠杆）。"""
        out: List[schemas.Suggestion] = []
        add = self._greedy_add(leg, rs, pool, rules, as_of)
        if add is not None:
            out.append(add)
        remove = self._greedy_remove(leg, rs, pool, rules, as_of)
        if remove is not None:
            out.append(remove)
        return out

    def _greedy_add(
        self,
        leg: schemas.TeamTradeLeg,
        rs: SalaryRuleSet,
        pool: List[schemas.PlayerAsset],
        rules: schemas.LeagueSalaryRules,
        as_of: datetime,
    ) -> Optional[schemas.Suggestion]:
        """杠杆①：从同队候选池逐步加最便宜球员到 outgoing，直至通过。"""
        in_leg = {p.player_id for p in leg.outgoing} | {p.player_id for p in leg.incoming}
        candidates = [p for p in pool if p.player_id not in in_leg]
        candidates.sort(key=lambda p: p.guaranteed)  # 最便宜优先，改动最小
        added: List[str] = []
        cur = leg
        for p in candidates:
            cur = leg.model_copy(update={"outgoing": list(cur.outgoing) + [p]})
            added.append(p.player_id)
            mr = validate_leg(cur, rs, rules, as_of)
            if mr.legal:
                return schemas.Suggestion(
                    team_abbr=leg.team_abbr,
                    add_player_ids=added,
                    remove_player_ids=[],
                    passes=True,
                    residual_deficit=mr.deficit,
                )
        final = validate_leg(cur, rs, rules, as_of)
        return schemas.Suggestion(
            team_abbr=leg.team_abbr,
            add_player_ids=added,
            remove_player_ids=[],
            passes=False,
            residual_deficit=final.deficit,
        )

    def _greedy_remove(
        self,
        leg: schemas.TeamTradeLeg,
        rs: SalaryRuleSet,
        pool: List[schemas.PlayerAsset],
        rules: schemas.LeagueSalaryRules,
        as_of: datetime,
    ) -> Optional[schemas.Suggestion]:
        """杠杆②：从 incoming 逐步移除最贵球员，直至通过。"""
        candidates = sorted(leg.incoming, key=lambda p: p.guaranteed, reverse=True)
        removed: List[str] = []
        cur = leg
        for p in candidates:
            new_in = [x for x in cur.incoming if x.player_id != p.player_id]
            cur = leg.model_copy(update={"incoming": new_in})
            removed.append(p.player_id)
            mr = validate_leg(cur, rs, rules, as_of)
            if mr.legal:
                return schemas.Suggestion(
                    team_abbr=leg.team_abbr,
                    add_player_ids=[],
                    remove_player_ids=removed,
                    passes=True,
                    residual_deficit=mr.deficit,
                )
        final = validate_leg(cur, rs, rules, as_of)
        return schemas.Suggestion(
            team_abbr=leg.team_abbr,
            add_player_ids=[],
            remove_player_ids=removed,
            passes=False,
            residual_deficit=final.deficit,
        )


class ProposalGenerator:
    """交易方案生成（TRADE-07）。"""

    def generate(
        self,
        target_player_id: str,
        initiator_team: str,
        rs: SalaryRuleSet,
        rules: schemas.LeagueSalaryRules,
        season: str,
        as_of: datetime,
    ) -> List[schemas.TradeProposal]:
        """给定目标球员 + 发起队，搜索可行的 2 队交易方案（受深度上限约束）。

        返回已通过校验的 TradeProposal 列表（最多 10 条），按发起队送出额升序。
        """
        assets = db.load_players_by_ids([target_player_id], season)
        if target_player_id not in assets:
            return []
        target = assets[target_player_id]
        target_team = target.team_abbr

        if not initiator_team or initiator_team == target_team:
            initiator_team = self._default_initiator(target_team, season)

        rosters = db.load_team_players([initiator_team, target_team], season)
        payrolls = db.load_team_payrolls([initiator_team, target_team], season)
        init_pool = rosters.get(initiator_team, [])
        target_pool = rosters.get(target_team, [])

        # 发起队候选（Top-N，按保障额降序取前 N）
        init_candidates = sorted(init_pool, key=lambda p: -p.guaranteed)[
            : constants.GEN_CANDIDATE_TOP_N
        ]
        # 目标队可搭送的搭档（Top-N）
        target_partners = sorted(
            [p for p in target_pool if p.player_id != target_player_id],
            key=lambda p: -p.guaranteed,
        )[: constants.GEN_CANDIDATE_TOP_N]

        proposals: List[schemas.TradeProposal] = []
        branches = 0

        # 目标队送出组合：单独目标 / 目标 + 1 搭档
        target_out_options: List[List[schemas.PlayerAsset]] = [[target]]
        for partner in target_partners[: constants.GEN_MAX_PARTNERS_PER_TEAM]:
            target_out_options.append([target, partner])

        # 发起队送出组合：1 名 / 2 名（size2 受分支上限约束）
        init_combos: List[List[schemas.PlayerAsset]] = [
            [p] for p in init_candidates
        ]
        size2_limit = max(0, constants.GEN_MAX_BRANCHES - len(init_combos))
        pair_count = 0
        for i in range(len(init_candidates)):
            for j in range(i + 1, len(init_candidates)):
                init_combos.append([init_candidates[i], init_candidates[j]])
                pair_count += 1
                if pair_count >= size2_limit:
                    break
            if pair_count >= size2_limit:
                break

        for combo in init_combos:
            if branches >= constants.GEN_MAX_BRANCHES:
                break
            init_out_total = sum(p.guaranteed for p in combo)
            for t_out in target_out_options:
                branches += 1
                if branches > constants.GEN_MAX_BRANCHES:
                    break
                init_leg = schemas.TeamTradeLeg(
                    team_abbr=initiator_team,
                    season=season,
                    outgoing=list(combo),
                    incoming=[target],
                    pre_trade_salary=payrolls.get(initiator_team, {}).get("totals", {}).get(season, 0),
                )
                target_leg = schemas.TeamTradeLeg(
                    team_abbr=target_team,
                    season=season,
                    outgoing=list(t_out),
                    incoming=list(combo),
                    pre_trade_salary=payrolls.get(target_team, {}).get("totals", {}).get(season, 0),
                )
                init_mr = validate_leg(init_leg, rs, rules, as_of)
                target_mr = validate_leg(target_leg, rs, rules, as_of)
                if init_mr.legal and target_mr.legal:
                    proposals.append(
                        schemas.TradeProposal(
                            league="NBA",
                            season=season,
                            as_of=as_of,
                            legs=[init_leg, target_leg],
                        )
                    )
            if len(proposals) >= 10:
                break

        proposals.sort(key=lambda p: sum(x.guaranteed for x in p.legs[0].outgoing))
        return proposals

    @staticmethod
    def _default_initiator(target_team: str, season: str) -> str:
        """无发起队时：取薪资最低（空间最大）的非目标队作为默认发起方。"""
        all_pay = db.load_team_payrolls(
            [t for t in _ALL_TEAM_ABBR if t != target_team], season
        )
        if not all_pay:
            return target_team
        best = min(
            all_pay.values(),
            key=lambda d: d.get("totals", {}).get(season, 0),
        )
        return best["team_abbr"]


# 30 队标准缩写（BRK 非 BKN，见 architecture §八）
_ALL_TEAM_ABBR = [
    "ATL", "BOS", "BRK", "CHO", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]
