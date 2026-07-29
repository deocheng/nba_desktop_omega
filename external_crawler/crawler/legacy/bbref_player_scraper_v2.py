#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 basketball_reference_web_scraper 库爬取所有NBA球员数据
"""
import pandas as pd
import logging
from pathlib import Path
import time
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from basketball_reference_web_scraper import client
    from basketball_reference_web_scraper.data import Team
    print("✓ basketball_reference_web_scraper 库已安装")
except ImportError as e:
    logger.error(f"未安装 basketball_reference_web_scraper 库: {e}")
    logger.info("请运行: pip install basketball_reference_web_scraper")
    exit(1)

def get_all_players():
    """获取所有NBA球员数据"""
    logger.info("开始获取所有NBA球员数据...")
    
    players = []
    
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        try:
            logger.info(f"获取字母 '{letter}' 开头的球员...")
            letter_players = client.players_whose_last_name_begins_with(letter)
            
            for player in letter_players:
                players.append({
                    'player_id': player['slug'],
                    'first_name': player['first_name'],
                    'last_name': player['last_name'],
                    'full_name': f"{player['first_name']} {player['last_name']}",
                    'position': player['position'],
                    'height': player['height'],
                    'weight': player['weight'],
                    'date_of_birth': player['date_of_birth'].isoformat() if player['date_of_birth'] else None,
                    'rookie_year': player['rookie_year'],
                    'final_year': player['final_year'],
                    'is_active': player['is_active']
                })
            
            logger.info(f"字母 '{letter}' 找到 {len(letter_players)} 名球员")
            
            time.sleep(random.uniform(1, 2))
            
        except Exception as e:
            logger.error(f"获取字母 '{letter}' 的球员失败: {e}")
    
    logger.info(f"总共获取到 {len(players)} 名球员")
    return players

def save_player_data(players):
    """保存球员数据到CSV文件"""
    output_path = Path('player_data')
    output_path.mkdir(parents=True, exist_ok=True)
    
    df = pd.DataFrame(players)
    output_file = output_path / 'bbref_all_players.csv'
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    logger.info(f"球员数据已保存到: {output_file}")
    
    return output_file

def get_player_career_stats(player_slug):
    """获取球员职业生涯统计数据"""
    try:
        stats = client.regular_season_player_stats(player_slug=player_slug)
        return stats
    except Exception as e:
        logger.error(f"获取球员 {player_slug} 的统计数据失败: {e}")
        return None

def main():
    print("=== Basketball Reference 球员数据爬取器 ===")
    print("1. 获取所有球员列表")
    print("2. 获取球员详细统计数据")
    print("3. 全部获取")
    
    choice = input("请选择操作 (1/2/3): ").strip()
    
    if choice == '1' or choice == '3':
        print("开始获取所有球员列表...")
        players = get_all_players()
        save_player_data(players)
        
        if choice == '1':
            print(f"\n✓ 已成功获取 {len(players)} 名球员")
            return
    
    if choice == '2' or choice == '3':
        players_df = pd.read_csv('player_data/bbref_all_players.csv')
        print(f"\n开始获取 {len(players_df)} 名球员的详细统计数据...")
        
        output_path = Path('player_data') / 'players'
        output_path.mkdir(parents=True, exist_ok=True)
        
        success_count = 0
        fail_count = 0
        
        for idx, row in players_df.iterrows():
            player_slug = row['player_id']
            player_name = row['full_name']
            
            try:
                stats = get_player_career_stats(player_slug)
                if stats:
                    stats_df = pd.DataFrame(stats)
                    stats_df.to_csv(output_path / f"{player_slug}_stats.csv", index=False, encoding='utf-8-sig')
                    success_count += 1
                
                time.sleep(random.uniform(0.5, 1.5))
                
                if (idx + 1) % 50 == 0:
                    print(f"进度: [{idx+1}/{len(players_df)}] 成功: {success_count}, 失败: {fail_count}")
            
            except Exception as e:
                fail_count += 1
        
        print(f"\n✓ 爬取完成! 成功: {success_count}, 失败: {fail_count}")

if __name__ == "__main__":
    main()