#!/usr/bin/env python3
"""
NBA 数据库完整补全计划分析脚本
- 审计 37 张表的数据覆盖
- 识别可从现有数据推导的缺口
- 制定补全优先级
- 设计 BR 验证方案
"""

import psycopg2
from psycopg2 import sql
from datetime import datetime

DB_CONFIG = {
    'host': 'localhost',
    'port': 5433,
    'dbname': 'nba',
    'user': 'postgres',
    'password': 'postgres'
}

COMPLETE_80 = set(range(1947, 2027))  # 1947-2026 = 80 seasons

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def audit_table(tbl_name):
    """审计单张表，返回 (row_count, season_min, season_max, season_count, error)"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # 行数
        cur.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(tbl_name)))
        cnt = cur.fetchone()[0]
        
        # 赛季覆盖
        season_info = None
        try:
            cur.execute(sql.SQL(
                'SELECT MIN(season), MAX(season), COUNT(DISTINCT season) '
                'FROM {} WHERE season IS NOT NULL'
            ).format(sql.Identifier(tbl_name)))
            r = cur.fetchone()
            if r[0]:
                season_info = {
                    'min': r[0],
                    'max': r[1],
                    'count': r[2],
                    'missing': sorted(COMPLETE_80 - set(range(r[0], r[1]+1)))
                }
        except Exception:
            pass
        
        conn.close()
        return {'rows': cnt, 'seasons': season_info, 'error': None}
    except Exception as e:
        return {'rows': None, 'seasons': None, 'error': str(e)[:100]}

def main():
    print('开始审计数据库...')
    
    tables = [
        # Games (6)
        ('games', '比赛基础信息'),
        ('game_metadata', '比赛元数据'),
        ('game_id_mapping', 'Game ID映射'),
        ('player_game_details', '球员比赛详情'),
        # PBP (2)
        ('play_by_play', 'PBP主表'),
        ('play_by_play_api', 'PBP API'),
        # Player (7)
        ('player_per_game', '球员场均'),
        ('player_advanced', '球员高阶'),
        ('player_totals', '球员总计'),
        ('player_per_100_poss', '每100回合'),
        ('player_per_36_minutes', '每36分钟'),
        ('player_shooting', '投篮详情'),
        ('player_play_by_play', '球员PBP'),
        # Team (4)
        ('team_stats_per_game', '球队场均'),
        ('team_totals', '球队总计'),
        ('team_summaries', '球队汇总'),
        ('team_stats_per_100_poss', '球队每100回合'),
        # Reference (5)
        ('team_mapping', '球队映射'),
        ('league_averages', '联盟平均'),
        ('draft_pick_history', '选秀历史'),
        ('all_star_selections', '全明星'),
        ('end_of_season_teams', '赛季荣誉'),
        # Draft (3)
        ('draft_picks', '选秀记录'),
        ('draft_summary', '选秀汇总'),
        # Salary (2)
        ('player_contracts_league', '球员合同'),
        ('team_payroll', '球队薪资'),
        # Player 扩展 (3)
        ('player_award_shares', '奖项投票'),
        ('player_gamelog', '球员比赛日志'),
        ('player_season_info', '球员赛季信息'),
        ('player_name_map', '球员姓名映射'),
        # Other (3)
        ('injuries', '伤病'),
        ('transactions', '交易'),
        ('starting_lineups', '首发阵容'),
        ('crawl_failures', '爬取失败记录'),
        # 新增 (2)
        ('player_season_splits', '球员拆分'),
        ('team_depth_chart', '球队深度图'),
    ]
    
    results = {}
    for tbl, desc in tables:
        r = audit_table(tbl)
        results[tbl] = {'desc': desc, **r}
        status = '✓' if r['error'] is None else '✗'
        print(f'  {status} {tbl:35s} {r["rows"] or "ERR":>12}')
    
    # 生成补全计划文档
    print('\n生成补全计划文档...')
    generate_completion_plan(results)
    print('完成！文档: docs/data_completion_plan.md')

def generate_completion_plan(results):
    """生成完整的数据补全计划文档"""
    
    with open('docs/data_completion_plan.md', 'w', encoding='utf-8') as f:
        f.write('# NBA 数据库完整补全计划\n')
        f.write(f'> 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}\n')
        f.write('> 核心策略：**数据库推导优先，BR爬取补充，交叉验证质量**\n\n')
        
        f.write('---\n\n')
        f.write('## 一、数据库现状总览（37张表）\n\n')
        
        # 分类统计
        categories = {
            '✅ 完整（80季无缺失）': [],
            '⚠️ 部分缺失（缺失<30季）': [],
            '❌ 严重缺失（缺失≥30季）': [],
            '🆕 仅当前/近期数据': [],
            '📭 空表/几乎空': [],
            '❓ 无season列': [],
        }
        
        for tbl, r in results.items():
            if r['error']:
                categories['📭 空表/几乎空'].append(tbl)
                continue
            
            s = r['seasons']
            if s is None:
                categories['❓ 无season列'].append(tbl)
            elif s['count'] == 80 and len(s['missing']) == 0:
                categories['✅ 完整（80季无缺失）'].append(tbl)
            elif len(s['missing']) < 30:
                categories['⚠️ 部分缺失（缺失<30季）'].append(tbl)
            elif s['count'] <= 5:
                categories['🆕 仅当前/近期数据'].append(tbl)
            else:
                categories['❌ 严重缺失（缺失≥30季）'].append(tbl)
        
        # 输出分类
        for cat, tbls in categories.items():
            if tbls:
                f.write(f'### {cat}\n\n')
                for tbl in sorted(tbls):
                    r = results[tbl]
                    if r['seasons']:
                        s = r['seasons']
                        f.write(f'- **{tbl}**: {r["rows"]:,} 行, 赛季 {s["min"]}-{s["max"]} ({s["count"]}季), 缺{len(s["missing"])}季\n')
                    else:
                        f.write(f'- **{tbl}**: {r["rows"]:,} 行 (无season列)\n')
                f.write('\n')
        
        f.write('---\n\n')
        f.write('## 二、可推导性分析（数据库内补全）\n\n')
        
        # 可推导场景
        derivable = [
            {
                'target': 'player_season_splits (主客场/月/星期拆分)',
                'source': 'player_gamelog JOIN games',
                'coverage': '2001-2026 (26季)',
                'method': 'GROUP BY player, team, split_type (home/away)',
                'priority': 'P0 - 已完成',
                'status': '✅ player_season_splits 已创建，28,551行'
            },
            {
                'target': 'team_depth_chart (球队深度图)',
                'source': 'starting_lineups',
                'coverage': '仅2025赛季',
                'method': '统计首发次数排名',
                'priority': 'P0 - 已完成',
                'status': '✅ team_depth_chart 已创建，655行'
            },
            {
                'target': 'game_id_mapping 补全',
                'source': 'games 表 game_id → 生成 BR 格式',
                'coverage': '2024-2026 (可从 games 推导)',
                'method': 'game_id 8位 → BR格式 (YYYYMMDD0TEAM)',
                'priority': 'P1 - 可推导',
                'status': '⏳ 待实现'
            },
            {
                'target': 'player_gamelog 历史补全 (2002-2003稀疏)',
                'source': 'play_by_play 聚合',
                'coverage': '可推导60-70%字段 (PTS/REB/AST/STL/BLK/TOV/PF)',
                'method': 'PBP事件聚合到球员-比赛级别',
                'priority': 'P1 - 可部分推导',
                'status': '⏳ 待实现 (AST/STL/BLK需BR补充)'
            },
            {
                'target': 'player_game_details 扩展赛季覆盖',
                'source': 'player_gamelog + games',
                'coverage': '可从 gamelog 推导比赛详情',
                'method': 'JOIN games 获取 season, 聚合',
                'priority': 'P2 - 可推导',
                'status': '⏳ 待分析'
            },
            {
                'target': 'team_game_splits (球队主客场拆分)',
                'source': 'games 表',
                'coverage': '200-2026 (完整)',
                'method': '简单聚合 home_away = home_team/away_team',
                'priority': 'P0 - 可推导',
                'status': '⏳ 待实现'
            },
        ]
        
        f.write('| 目标表/数据 | 数据源 | 覆盖范围 | 方法 | 优先级 | 状态 |\n')
        f.write('|------------|--------|----------|------|--------|------|\n')
        for d in derivable:
            f.write(f'| {d["target"]} | {d["source"]} | {d["coverage"]} | {d["method"]} | {d["priority"]} | {d["status"]} |\n')
        
        f.write('\n---\n\n')
        f.write('## 三、必须爬取的数据（BR补充）\n\n')
        
        must_crawl = [
            {
                'target': 'player_gamelog 2026赛季补全',
                'reason': 'PBP无法推导AST/STL/BLK，必须爬取',
                'source': 'BR players/{id}.html gamelog',
                'priority': 'P1 - 高',
                'status': '🔄 后台爬取中 (crawl_br_gamelog.py)',
                'estimate': '55分钟, 556名球员'
            },
            {
                'target': 'transactions 历史补全 (1947-2024)',
                'reason': '交易记录无替代来源',
                'source': 'BR leagues/NBA_{year}_transactions.html',
                'priority': 'P1 - 高',
                'status': '⏳ 待爬取',
                'estimate': '80个页面, ~2小时'
            },
            {
                'target': 'injuries 历史补全',
                'reason': '伤病记录无替代来源',
                'source': 'BR friv/injuries.fcgi?year={year}',
                'priority': 'P2 - 中',
                'status': '⏳ 待爬取',
                'estimate': '80个页面, ~1小时'
            },
            {
                'target': 'coach_data (教练数据)',
                'reason': '无教练表，BR有完整coaches页面',
                'source': 'BR coaches/{coach_id}.html',
                'priority': 'P2 - 中',
                'status': '❓ 需新建表+爬虫',
                'estimate': '需先发现教练列表页'
            },
            {
                'target': 'player_splits (详细拆分)',
                'reason': 'BR有location/split页面，细分到对手/月份/星期',
                'source': 'BR players/{id}/splits.html',
                'priority': 'P3 - 低',
                'status': '⏳ 待爬取',
                'estimate': '572名球员, ~5小时'
            },
            {
                'target': 'game_id_mapping 历史补全 (1947-2023)',
                'reason': 'games表有历史数据，但mapping表只有2025-2026',
                'source': '从games派生 + BR验证',
                'priority': 'P2 - 中',
                'status': '⏳ 待推导+验证',
                'estimate': '可100%推导'
            },
        ]
        
        f.write('| 目标数据 | 原因 | 数据源 | 优先级 | 状态 | 预估时间 |\n')
        f.write('|----------|------|--------|--------|------|----------|\n')
        for m in must_crawl:
            f.write(f'| {m["target"]} | {m["reason"]} | {m["source"]} | {m["priority"]} | {m["status"]} | {m["estimate"]} |\n')
        
        f.write('\n---\n\n')
        f.write('## 四、BR验证方案（确保数据质量）\n\n')
        
        validation_plan = [
            {
                'table': 'player_gamelog',
                'br_source': 'BR players/{id}.html gamelog',
                'validate_fields': 'pts, reb, ast, stl, blk, tov, pf, mins',
                'method': '随机抽取100场比赛，对比BR与DB',
                'frequency': '每次大批量爬取后',
            },
            {
                'table': 'player_per_game (推导字段)',
                'br_source': 'BR players/{id}.html',
                'validate_fields': 'pts, reb, ast, fg_pct, fg3_pct, ft_pct',
                'method': '对比BR页面与DB中player_per_game表',
                'frequency': '赛季结束后抽样验证',
            },
            {
                'table': 'transactions',
                'br_source': 'BR transactions页面',
                'validate_fields': 'date, type, teams, players',
                'method': '逐页对比BR与DB记录',
                'frequency': '每次爬取后全量对比',
            },
            {
                'table': 'team_payroll',
                'br_source': 'BR contracts/{abbr}.html',
                'validate_fields': 'salary, season, player',
                'method': '对比BR合同页与DB薪资数据',
                'frequency': '每周爬取后验证',
            },
        ]
        
        f.write('| 数据表 | BR来源 | 验证字段 | 方法 | 频率 |\n')
        f.write('|--------|--------|----------|------|------|\n')
        for v in validation_plan:
            f.write(f'| {v["table"]} | {v["br_source"]} | {v["validate_fields"]} | {v["method"]} | {v["frequency"]} |\n')
        
        f.write('\n---\n\n')
        f.write('## 五、执行计划（分阶段）\n\n')
        
        phases = [
            {
                'phase': 'Phase 1: 数据库内推导补全（0爬取）',
                'tasks': [
                    '✅ player_season_splits 已创建 (P3-A完成)',
                    '✅ team_depth_chart 已创建 (P3-C完成)',
                    '⏳ game_id_mapping 从 games 表推导 (P1)',
                    '⏳ team_game_splits 从 games 表聚合 (P0)',
                    '⏳ player_career_totals 从 player_gamelog 聚合 (P1)',
                ],
                'dependencies': '无',
                'estimate': '2小时',
            },
            {
                'phase': 'Phase 2: BR爬取补全（高优先级）',
                'tasks': [
                    '🔄 player_gamelog 2026赛季补全 (进行中)',
                    '⏳ transactions 1947-2024 历史补全 (P1)',
                    '⏳ injuries 历史补全 (P2)',
                ],
                'dependencies': 'Phase 1完成',
                'estimate': '4小时',
            },
            {
                'phase': 'Phase 3: BR验证 + 数据质量修复',
                'tasks': [
                    '⏳ 验证 player_gamelog 与 BR 一致性',
                    '⏳ 验证 transactions 完整性',
                    '⏳ 修复发现的差异',
                ],
                'dependencies': 'Phase 2完成',
                'estimate': '2小时',
            },
            {
                'phase': 'Phase 4: 扩展数据（低优先级）',
                'tasks': [
                    '⏳ coach_data 表创建 + 爬虫',
                    '⏳ player_splits 详细拆分爬取',
                    '⏳ play_by_play 历史扩展 (1947-2000)',
                ],
                'dependencies': 'Phase 3完成',
                'estimate': '8小时',
            },
        ]
        
        for p in phases:
            f.write(f'### {p["phase"]}\n')
            f.write(f'**依赖**: {p["dependencies"]}  \n')
            f.write(f'**预估时间**: {p["estimate"]}  \n\n')
            for task in p['tasks']:
                f.write(f'- {task}\n')
            f.write('\n')
        
        f.write('---\n\n')
        f.write('## 六、自动化任务注册计划\n\n')
        
        automation_plan = [
            {
                'name': '每日games结果更新',
                'schedule': '每天 10:00',
                'source': 'data.nba.com API',
                'target': 'games, game_metadata',
                'priority': 'P0',
            },
            {
                'name': '每日player_gamelog更新',
                'schedule': '每天 10:30',
                'source': 'BR gamelog',
                'target': 'player_gamelog',
                'priority': 'P0',
            },
            {
                'name': '每日injuries更新',
                'schedule': '每天 10:30',
                'source': 'BR injuries',
                'target': 'injuries',
                'priority': 'P1',
            },
            {
                'name': '每周transactions更新',
                'schedule': '每周一 10:30',
                'source': 'BR transactions',
                'target': 'transactions',
                'priority': 'P1',
            },
            {
                'name': '每月salary更新',
                'schedule': '每月1日 10:00',
                'source': 'BR contracts',
                'target': 'team_payroll, player_contracts_league',
                'priority': 'P2',
            },
        ]
        
        f.write('| 任务名 | 频率 | 数据源 | 目标表 | 优先级 |\n')
        f.write('|--------|------|--------|----------|--------|\n')
        for a in automation_plan:
            f.write(f'| {a["name"]} | {a["schedule"]} | {a["source"]} | {a["target"]} | {a["priority"]} |\n')
        
        f.write('\n---\n\n')
        f.write('## 七、风险与缓解措施\n\n')
        f.write('1. **BR反爬虫**: LightScraper已验证可用（3-6s延迟+随机UA），如被封禁则切换Playwright  \n')
        f.write('2. **数据一致性**: 每次BR爬取后运行验证脚本，对比抽样数据  \n')
        f.write('3. **PBP推导准确性**: AST/STL/BLK无法从PBP推导，必须BR补充  \n')
        f.write('4. **历史数据缺失**: 1947-2000年部分数据BR也无记录，标记为"unavailable"  \n')
        f.write('5. **性能**: 大批量爬取时启用--resume模式，避免重复爬取  \n')
        f.write('\n')
        
        f.write('---\n\n')
        f.write('## 八、成功指标\n\n')
        f.write('- [ ] 37张表全部审计完成  \n')
        f.write('- [ ] player_gamelog 2026赛季覆盖率 >95%  \n')
        f.write('- [ ] transactions 历史覆盖 >70季 (1947-2024)  \n')
        f.write('- [ ] injuries 历史覆盖 >50季  \n')
        f.write('- [ ] game_id_mapping 覆盖 >50季  \n')
        f.write('- [ ] BR验证通过率 >98%  \n')
        f.write('- [ ] 自动化任务全部注册并运行成功  \n')
        f.write('\n')
        
        f.write(f'> 文档生成: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')

if __name__ == '__main__':
    main()
