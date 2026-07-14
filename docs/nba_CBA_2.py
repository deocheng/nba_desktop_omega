from dataclasses import dataclass
from typing import List, Dict, Optional
import json

# ====================== NBA CBA 核心常量（2025-26赛季示例数据） ======================
SALARY_CAP = 154_647_000          # 薪金帽
LUXURY_TAX_THRESHOLD = 187_895_000  # 奢侈税线 ≈ 121.5% of cap
FIRST_APRON = 172_346_000 + 10_000_000  # 第一围裙（示例，实际以当年为准）
SECOND_APRON = 182_794_000 + 10_000_000 # 第二围裙（更严厉限制）

MIN_TEAM_SALARY_PCT = 0.90        # 最低球队薪资 = 90% of Salary Cap

# 奢侈税税率（非重复犯规）
LUXURY_TAX_RATES = [
    (5_000_000, 1.50),   # 0-5M over: $1.50 per dollar
    (10_000_000, 1.75),  # 5-10M: $1.75
    (15_000_000, 2.00),
    (20_000_000, 2.25),
    (float('inf'), 2.50) # 更高继续递增
]

# 重复犯规（最近4年交税3次）税率更高，从$2.50开始

@dataclass
class Player:
    name: str
    salary: int
    years_of_service: int  # YOS，用于Bird Rights和Max Salary
    bird_rights: bool = False  # 是否拥有Bird Rights
    contract_years_left: int = 1

class NBATeam:
    def __init__(self, name: str):
        self.name = name
        self.roster: List[Player] = []
        self.cap_holds: Dict[str, int] = {}  # 自由球员Cap Hold
    
    def add_player(self, player: Player):
        self.roster.append(player)
    
    def total_salary(self) -> int:
        return sum(p.salary for p in self.roster)
    
    def is_over_cap(self) -> bool:
        return self.total_salary() > SALARY_CAP
    
    def luxury_tax_bill(self) -> int:
        """计算奢侈税"""
        over = self.total_salary() - LUXURY_TAX_THRESHOLD
        if over <= 0:
            return 0
        
        tax = 0
        prev_threshold = 0
        for threshold, rate in LUXURY_TAX_RATES:
            segment = min(over, threshold - prev_threshold)
            if segment > 0:
                tax += int(segment * rate)
            if over <= threshold:
                break
            prev_threshold = threshold
            over -= segment
        return tax
    
    def status(self):
        total = self.total_salary()
        print(f"\n=== {self.name} ===")
        print(f"总薪资: ${total:,}")
        print(f"薪金帽情况: {'低于' if total <= SALARY_CAP else '超过'} (${SALARY_CAP:,})")
        print(f"奢侈税: ${self.luxury_tax_bill():,}")
        
        if total > SECOND_APRON:
            print("⚠️ 超过第二围裙：受严厉限制（硬帽、选秀权惩罚等）")
        elif total > FIRST_APRON:
            print("⚠️ 超过第一围裙：受部分限制")
        elif total > LUXURY_TAX_THRESHOLD:
            print("超过奢侈税线")


# ====================== 辅助函数 ======================
def calculate_min_team_salary():
    return int(SALARY_CAP * MIN_TEAM_SALARY_PCT)

def get_minimum_salary(yos: int, season: str = "2025-26") -> int:
    """简化版最低薪资（实际每年有表格）"""
    base = 1_000_000
    return base + yos * 300_000  # 粗略公式，真实用官方表格

def max_salary(yos: int, is_supermax: bool = False) -> int:
    """最大合同简化版"""
    if yos >= 10:
        pct = 0.35 if is_supermax else 0.30
    elif yos >= 7:
        pct = 0.30 if is_supermax else 0.25
    else:
        pct = 0.25
    return int(SALARY_CAP * pct)

# ====================== 示例使用 ======================
if __name__ == "__main__":
    warriors = NBATeam("Golden State Warriors")
    
    # 添加球员
    warriors.add_player(Player("Stephen Curry", 55_000_000, 16, bird_rights=True))
    warriors.add_player(Player("Draymond Green", 25_000_000, 12, bird_rights=True))
    warriors.add_player(Player("Jonathan Kuminga", 8_000_000, 3))
    warriors.add_player(Player("Role Player", 4_000_000, 5))
    
    warriors.status()
    
    print(f"\n全联盟最低球队薪资要求: ${calculate_min_team_salary():,}")
    print(f"10年老将最高薪: ${max_salary(10):,}")
    print(f"10年老将Supermax: ${max_salary(10, True):,}")
    
    # 保存为JSON示例（可用于更大模拟）
    team_data = {
        "team": warriors.name,
        "total_salary": warriors.total_salary(),
        "over_cap": warriors.is_over_cap(),
        "luxury_tax": warriors.luxury_tax_bill()
    }
    print("\nJSON输出示例:", json.dumps(team_data, indent=2))