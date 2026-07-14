"""NBACore v8 — AI 交易语义解析：Prompt 模板（few-shot JSON 抽取）。

仅依赖标准库风格文本拼接，无第三方依赖。system / user prompt 要求模型
仅输出严格 JSON，从 NBA 交易自由文本抽取对手方 / 送出球员 / 换入球员 /
选秀权 / 现金 / 备注。
"""
from __future__ import annotations

from typing import Dict, List, Optional

SYSTEM_PROMPT = """You are an NBA trade semantics extractor. \
Given a free-text description of an NBA trade, output ONLY a single strict JSON object \
(no markdown, no commentary) with exactly these keys:

- "counterparties": array of NBA team abbreviations (e.g. "GSW", "DEN") or full names; prefer abbreviations.
- "players_out": array of player names sent AWAY by the related team.
- "players_in": array of player names RECEIVED by the related team.
- "picks": array of draft-pick descriptions (e.g. "2026 first-round pick (LAL)").
- "cash": number (USD) if cash is involved, otherwise null.
- "notes": string with any residual/unclassified details, otherwise "".

Rules:
1. Output ONLY the JSON object. No prose, no code fences.
2. If a field is absent, use an empty array or null as appropriate.
3. Team abbreviations should match standard 3-letter NBA codes when identifiable.
"""


def build_user_prompt(text: str, team_abbr: Optional[str] = None) -> str:
    """构造 user prompt：few-shot 示例 + 实际输入 + 关联球队 hint。"""
    hint = team_abbr if team_abbr else "unknown"
    return f"""Examples:

Example 1
Input: "Orlando Magic traded Aaron Gordon to Denver Nuggets for Gary Harris"
Output: {{"counterparties":["ORL","DEN"],"players_out":["Aaron Gordon"],"players_in":["Gary Harris"],"picks":[],"cash":null,"notes":""}}

Example 2
Input: "The Golden State Warriors traded James Wiseman to the Detroit Pistons for a 2023 second-round pick"
Output: {{"counterparties":["GSW","DET"],"players_out":["James Wiseman"],"players_in":[],"picks":["2023 second-round pick"],"cash":null,"notes":""}}

Example 3
Input: "Brooklyn Nets traded Kevin Durant and T.J. Warren to Phoenix Suns for Mikal Bridges, Cameron Johnson, Jae Crowder and a 2023 first-round pick; $5 million traded"
Output: {{"counterparties":["BKN","PHX"],"players_out":["Kevin Durant","T.J. Warren"],"players_in":["Mikal Bridges","Cameron Johnson","Jae Crowder"],"picks":["2023 first-round pick"],"cash":5000000,"notes":"$5 million traded"}}

Now extract the following trade:
Related team hint: {hint}
Input: {text}
Output:"""


def build_messages(text: str, team_abbr: Optional[str] = None) -> List[Dict[str, str]]:
    """返回 Ollama /api/chat 的 messages 列表 [system, user]。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(text, team_abbr)},
    ]
