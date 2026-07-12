"""NBACore v8 — Trade Engine 补充模块 (cba_aux)

v8.3.2+ 补充模块: Bird Rights cap hold + Player max salary % + 多队 League 模拟。
``trade_engine`` 现有 ``nba_rules.py`` 的交易校验/税档计算互不重叠，互补。

定位
----
本模块为纯算法层，零 SQL、零 DB 写、零外部依赖（仅 Python stdlib）。
与现有 ``nba_rules.py`` / ``tax_engine.py`` 的关系:

- ``nba_rules.py`` 实现 ``NBARuleSet``（可插拔规则引擎，作用于 ``PlayerAsset`` /
  ``LeagueSalaryRules``），负责交易 leg 的 apron / cap / tax 校验。
- ``tax_engine.py`` 实现 cap impact / tax bill 评估。
- ``cba_aux.py``（本模块）实现:

    1. Bird Rights cap hold - 自由球员 cap hold 倍乘数
       (Full Bird 1.50x / Early Bird 1.25x / Non-Bird 1.20x)。
    2. Player max salary % - 按 yos + All-NBA 决定顶薪比例
       (25% / 30% / 35%)。
    3. LeagueSimulator - 多队赛季模拟 + JSON 持久化。

金额约定
-------
全部金额仍用 ``int``（美元整数，无小数），与 trade_engine 整体一致。

使用
---
本模块可直接作为离线分析 CLI 运行:
    python -m backend.services.trade_engine.cba_aux
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple


# ====================== 2026-2027 赛季预估规则 ======================
@dataclass
class SalaryCapRules:
    """2026-2027 赛季预估薪资规则常量。

    字段:
        base_cap:        基础工资帽（美元整数）
        luxury_tax_line: 奢侈税起征线（缺省 = base_cap * 1.215）
        first_apron:     第一围裙（缺省 = luxury_tax_line + 6M）
        second_apron:    第二围裙（缺省 = luxury_tax_line + 17.5M）
        min_team_salary: 球队最低薪资总额（缺省 = base_cap * 0.90）
    """

    base_cap: int = 168_000_000
    luxury_tax_line: int = None  # type: ignore[assignment]
    first_apron: int = None  # type: ignore[assignment]
    second_apron: int = None  # type: ignore[assignment]
    min_team_salary: int = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.luxury_tax_line is None:
            self.luxury_tax_line = int(self.base_cap * 1.215)
        if self.first_apron is None:
            self.first_apron = self.luxury_tax_line + 6_000_000
        if self.second_apron is None:
            self.second_apron = self.luxury_tax_line + 17_500_000
        if self.min_team_salary is None:
            self.min_team_salary = int(self.base_cap * 0.90)


# ====================== Player & Bird Rights ======================
@dataclass
class Player:
    """球员基础信息 + Bird Rights 归属 + 顶薪档位判定。

    字段:
        name:                   球员姓名（roster key）
        salary:                 当前赛季薪资（美元整数）
        yos:                    years of service（资历年数）
        is_all_nba:             当季是否入选 All-NBA
        contract_years_left:    合同剩余年限
        bird_rights_with_team:  当前拥有 Bird Rights 的球队名
    """

    name: str
    salary: int
    yos: int = 0
    is_all_nba: bool = False
    contract_years_left: int = 1
    bird_rights_with_team: Optional[str] = None

    def get_max_salary_pct(self) -> float:
        """根据 yos + All-NBA 状态计算顶薪占工资帽比例。

        规则:
            yos >= 10 且 All-NBA  -> 0.35
            yos <  10 且 All-NBA  -> 0.30
            其余                  -> 0.25
        """
        if self.yos >= 10 and self.is_all_nba:
            return 0.35
        if self.is_all_nba:
            return 0.30
        return 0.25


# ====================== Team ======================
class Team:
    """NBA 球队: roster + cap_holds + repeat payer 标记。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.roster: Dict[str, Player] = {}
        self.cap_holds: Dict[str, int] = {}
        self.is_repeat_luxury_payer: bool = False

    def add_player(self, player: Player) -> None:
        """加入 roster 并把 bird_rights_with_team 标记为本队。"""
        self.roster[player.name] = player
        player.bird_rights_with_team = self.name

    def total_salary(self) -> int:
        """roster 中所有球员薪资之和（美元整数）。"""
        return sum(p.salary for p in self.roster.values())

    def get_cap_hold(self, player: Player) -> int:
        """Bird Rights Cap Hold 倍乘数。

        规则:
            yos >= 3  -> Full Bird  = 1.50x
            yos >= 2  -> Early Bird = 1.25x
            其余      -> Non-Bird   = 1.20x
        """
        if player.yos >= 3:
            return int(player.salary * 1.50)
        elif player.yos >= 2:
            return int(player.salary * 1.25)
        else:
            return int(player.salary * 1.20)

    def renounce_bird_rights(self, player_name: str) -> None:
        """放弃指定球员的 Bird Rights。"""
        if player_name in self.cap_holds:
            del self.cap_holds[player_name]
        if player_name in self.roster:
            self.roster[player_name].bird_rights_with_team = None

    def to_dict(self) -> dict:
        """序列化为 dict（供 save_league 使用）。"""
        return {
            "name": self.name,
            "roster": {name: asdict(p) for name, p in self.roster.items()},
            "cap_holds": self.cap_holds,
            "is_repeat_luxury_payer": self.is_repeat_luxury_payer,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Team":
        """从 to_dict() 反序列化。"""
        team = cls(data["name"])
        for p_data in data["roster"].values():
            player = Player(**p_data)
            team.add_player(player)
        team.cap_holds = data["cap_holds"]
        team.is_repeat_luxury_payer = data["is_repeat_luxury_payer"]
        return team


# ====================== 交易模拟器 ======================
class TradeSimulator:
    """两队交易模拟器: 基于 apron 规则判定交易是否合法。"""

    @staticmethod
    def can_trade(
        team: Team,
        rules: SalaryCapRules,
        outgoing_salary: int,
        incoming_salary: int,
    ) -> Tuple[bool, str]:
        """判定指定球队在某次交易视角下是否合规。

        规则:
            - total > second_apron: 禁止接收更高薪资
            - first_apron < total <= second_apron: 100% 配平
            - total <= first_apron: 无 apron 限制
        """
        total = team.total_salary()

        if total > rules.second_apron:
            if incoming_salary > outgoing_salary:
                return False, "第二围裙球队禁止接收更高薪资"
            return True, "第二围裙硬帽限制通过"

        if total > rules.first_apron:
            if incoming_salary > outgoing_salary * 1.0:
                return False, "第一围裙限制:接收薪资不得超过送出薪资"

        return True, "交易通过"

    @staticmethod
    def execute_trade(
        team_a: Team,
        team_b: Team,
        players_a_to_b: List[str],
        players_b_to_a: List[str],
        rules: SalaryCapRules,
    ) -> bool:
        """两队之间执行交易。任一方 can_trade 失败即整体 fail。"""
        salary_a_out = sum(team_a.roster[p].salary for p in players_a_to_b)
        salary_b_out = sum(team_b.roster[p].salary for p in players_b_to_a)

        can_a, msg_a = TradeSimulator.can_trade(team_a, rules, salary_a_out, salary_b_out)
        can_b, msg_b = TradeSimulator.can_trade(team_b, rules, salary_b_out, salary_a_out)

        if not (can_a and can_b):
            print(f"交易失败: {msg_a} | {msg_b}")
            return False

        for p_name in players_a_to_b:
            player = team_a.roster.pop(p_name)
            team_b.add_player(player)

        for p_name in players_b_to_a:
            player = team_b.roster.pop(p_name)
            team_a.add_player(player)

        print(f"✅ 交易完成!{team_a.name} ↔ {team_b.name}")
        return True


# ====================== 多球队赛季模拟 ======================
class LeagueSimulator:
    """多队赛季模拟器 + JSON 持久化。"""

    def __init__(self) -> None:
        self.teams: Dict[str, Team] = {}
        self.rules = SalaryCapRules()

    def add_team(self, team: Team) -> None:
        self.teams[team.name] = team

    # 状态枚举 -> 中文打印标签（仅 season_summary 打印用；snapshot 返回英文枚举）
    _STATUS_CN = {
        "HEALTHY": "健康",
        "LUXURY_TAX": "奢侈税",
        "FIRST_APRON": "第一围裙",
        "SECOND_APRON": "第二围裙违规",
    }

    def _team_status(self, total: int) -> str:
        """按 total 与 self.rules 阈值判定球队状态（引擎层计算，供 snapshot 与 season_summary 共用）。

        判定顺序: second_apron > first_apron > luxury_tax_line > healthy。
        返回状态枚举字符串: HEALTHY / LUXURY_TAX / FIRST_APRON / SECOND_APRON。
        """
        if total > self.rules.second_apron:
            return "SECOND_APRON"
        if total > self.rules.first_apron:
            return "FIRST_APRON"
        if total > self.rules.luxury_tax_line:
            return "LUXURY_TAX"
        return "HEALTHY"

    def season_summary(self) -> None:
        """打印每队薪资 + 围裙/奢侈税状态（与 snapshot 共用 _team_status 判定）。"""
        print("\n" + "=" * 60)
        print("🏀 2026-2027 NBA 赛季薪资总结")
        print("=" * 60)
        for team in self.teams.values():
            total = team.total_salary()
            status = self._STATUS_CN[self._team_status(total)]
            print(f"{team.name:25} | 薪资 ${total:>10,} | {status}")

    def snapshot(self) -> dict:
        """结构化快照: 逐队 {team, total_salary, status}（status ∈ 状态枚举）。

        供 ``/cba/league/summary`` 使用（v8 §6: 计算留在引擎层，router 仅编排）。
        返回 ``{"teams": [{"team", "total_salary", "status"}, ...]}``。
        """
        teams = []
        for team in self.teams.values():
            total = team.total_salary()
            teams.append({
                "team": team.name,
                "total_salary": total,
                "status": self._team_status(total),
            })
        return {"teams": teams}

    def to_dict(self) -> dict:
        """序列化为 dict（供 /cba/league/export 使用，零后端写）。"""
        return {
            "rules": asdict(self.rules),
            "teams": {name: team.to_dict() for name, team in self.teams.items()},
        }

    def save_league(self, filename: str = "nba_league_2026.json") -> None:
        """把当前 league 状态写入 JSON 文件。"""
        data = {
            "rules": asdict(self.rules),
            "teams": {name: team.to_dict() for name, team in self.teams.items()},
        }
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 联盟数据已保存至 {filename}")

    @classmethod
    def load_league(cls, filename: str = "nba_league_2026.json") -> "LeagueSimulator":
        """从 JSON 文件加载 league 状态。"""
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        sim = cls()
        sim.rules = SalaryCapRules(**data["rules"])

        for t_data in data["teams"].values():
            team = Team.from_dict(t_data)
            sim.add_team(team)
        print(f"📂 已加载联盟存档 {filename}")
        return sim


# ====================== 使用示例 ======================
if __name__ == "__main__":
    sim = LeagueSimulator()

    warriors = Team("Golden State Warriors")
    lakers = Team("Los Angeles Lakers")

    warriors.add_player(Player("Stephen Curry", 62_000_000, 17, True, 2))
    warriors.add_player(Player("Draymond Green", 28_000_000, 13, False, 3))

    lakers.add_player(Player("LeBron James", 50_000_000, 23, True, 1))
    lakers.add_player(Player("Anthony Davis", 45_000_000, 13, True, 2))

    sim.add_team(warriors)
    sim.add_team(lakers)

    print("\n--- 交易模拟 ---")
    TradeSimulator.execute_trade(
        warriors,
        lakers,
        players_a_to_b=["Draymond Green"],
        players_b_to_a=["Anthony Davis"],
        rules=sim.rules,
    )

    sim.season_summary()
    sim.save_league()

    loaded = LeagueSimulator.load_league()
    loaded.season_summary()
