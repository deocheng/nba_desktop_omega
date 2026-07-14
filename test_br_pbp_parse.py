"""Unit-test the parsing functions against real BR PBP descriptions."""
from __future__ import annotations
from br_pbp_parse import extract_player, extract_action_verb, extract_subtype, classify

SAMPLES = [
    "Offensive rebound by Team",
    "L. Kennardmisses 2-pt layup from 2 ft (block byD. Sharpe)",
    "Offensive rebound byJ. Tyson",
    "Defensive rebound byC. Martin",
    "K. Porziņģismisses 2-pt jump shot from 17 ft",
    "D. Huntermakes 2-pt layup from 1 ft (assist byD. Wade)",
    "J. Smithmakes free throw 2 of 2",
    "Z. Risachermisses 2-pt hook shot from 10 ft",
    "Def 3 sec tech foul by Team",
    "G. Antetokounmpomisses 2-pt jump shot from 15 ft",
    "I. Zubacmakes 2-pt hook shot from 11 ft (assist byJ. Harden)",
    "D. Wademisses 3-pt jump shot from 26 ft",
    "P. Spencerenters the game forB. Podziemski",
    "Instant Replay",
    "J. Poolemakes 3-pt jump shot from 26 ft",
    "S. Fontecchiomisses 2-pt layup from 2 ft",
    "A. Thompsonmisses 2-pt layup from 2 ft (block byV. Wembanyama)",
    "A. Wigginsenters the game forC. Wallace",
    "Turnover byM. Porter(bad pass; steal byJ. Duren)",
    "Turnover byB. Hield(offensive foul)",
    "M. Christieenters the game forK. Thompson",
    "A. Blackmakes free throw 1 of 2",
    "Turnover byH. Barnes(bad pass; steal byS. Adams)",
    "E. Mobleymisses 2-pt jump shot from 5 ft",
]

print(f"{'player':18} {'verb':10} {'subtype':22} {'event_type':14} description")
print("-" * 100)
ok = 0
for s in SAMPLES:
    p = extract_player(s)
    v = extract_action_verb(s)
    st = extract_subtype(s, v)
    et, _ = classify(s)
    flag = "OK" if (p and v) or (not p and v in ('instant replay', 'period')) else "??"
    if flag == "OK":
        ok += 1
    print(f"{p[:17]:18} {str(v):10} {str(st)[:21]:22} {str(et)[:13]:14} {s[:40]}")

print(f"\n{ok}/{len(SAMPLES)} rows have both name+verb (or verb-only non-player event)")
# sanity: ensure no name still has a glued verb
print("\n=== glued-verb check (player should NOT end with a verb) ===")
bad = [s for s in SAMPLES if extract_player(s).lower().endswith(('enters','makes','misses','rebound','foul','turnover'))]
print("BAD names:", bad if bad else "none")
