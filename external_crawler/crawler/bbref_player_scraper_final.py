#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basketball Reference球员数据爬取器
使用 requests 和 BeautifulSoup 直接爬取网站
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
from pathlib import Path
from tqdm import tqdm

BASE_URL = "https://www.basketball-reference.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8"
}

def get_player_list_by_letter(letter):
    """获取指定字母开头的球员列表"""
    url = f"{BASE_URL}/players/{letter.lower()}/"
    
    try:
        time.sleep(random.uniform(2, 4))
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        table = soup.find('table', {'id': f'players_{letter.lower()}'})
        
        if not table:
            table = soup.find('table')
        
        if not table:
            return []
        
        players = []
        rows = table.find('tbody').find_all('tr')
        
        for row in rows:
            if row.get('class') and 'thead' in row.get('class'):
                continue
            
            name_cell = row.find('th', {'data-stat': 'player'})
            if not name_cell:
                continue
            
            player_name = name_cell.get_text(strip=True)
            player_link = name_cell.find('a')
            
            if player_link:
                player_url = BASE_URL + player_link['href']
                player_id = player_url.split('/')[-1].replace('.html', '')
            else:
                player_url = None
                player_id = None
            
            from_year = row.find('td', {'data-stat': 'year_min'})
            to_year = row.find('td', {'data-stat': 'year_max'})
            position = row.find('td', {'data-stat': 'pos'})
            height = row.find('td', {'data-stat': 'height'})
            weight = row.find('td', {'data-stat': 'weight'})
            birth_date = row.find('td', {'data-stat': 'birth_date'})
            colleges = row.find('td', {'data-stat': 'colleges'})
            
            players.append({
                'player_id': player_id,
                'player_name': player_name,
                'from_year': from_year.get_text(strip=True) if from_year else None,
                'to_year': to_year.get_text(strip=True) if to_year else None,
                'position': position.get_text(strip=True) if position else None,
                'height': height.get_text(strip=True) if height else None,
                'weight': weight.get_text(strip=True) if weight else None,
                'birth_date': birth_date.get_text(strip=True) if birth_date else None,
                'colleges': colleges.get_text(strip=True) if colleges else None,
                'player_url': player_url
            })
        
        return players
    
    except Exception as e:
        print(f"获取字母 '{letter}' 的球员失败: {e}")
        return []

def get_all_players():
    """获取所有字母开头的球员列表"""
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    all_players = []
    
    print("开始爬取所有NBA球员数据...")
    for letter in tqdm(letters, desc="处理字母"):
        players = get_player_list_by_letter(letter)
        all_players.extend(players)
        print(f"字母 '{letter}' 找到 {len(players)} 名球员")
    
    print(f"\n总共找到 {len(all_players)} 名球员")
    return all_players

def save_player_list(players, output_dir='player_data'):
    """保存球员列表到CSV文件"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    df = pd.DataFrame(players)
    output_file = output_path / 'bbref_all_players.csv'
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n球员列表已保存到: {output_file}")
    
    return output_file

def get_player_stats(player_url):
    """获取球员详细统计数据"""
    try:
        time.sleep(random.uniform(1, 3))
        response = requests.get(player_url, headers=HEADERS)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        player_data = {}
        
        per_game_table = soup.find('table', id='per_game')
        if per_game_table:
            per_game_data = []
            rows = per_game_table.find('tbody').find_all('tr')
            for row in rows:
                if row.get('class') and ('thead' in row.get('class') or 'over_header' in row.get('class')):
                    continue
                
                season_data = {}
                for cell in row.find_all(['th', 'td']):
                    stat = cell.get('data-stat')
                    value = cell.get_text(strip=True)
                    season_data[stat] = value
                
                if season_data:
                    per_game_data.append(season_data)
            player_data['per_game'] = per_game_data
        
        totals_table = soup.find('table', id='totals')
        if totals_table:
            totals_data = []
            rows = totals_table.find('tbody').find_all('tr')
            for row in rows:
                if row.get('class') and ('thead' in row.get('class') or 'over_header' in row.get('class')):
                    continue
                
                season_data = {}
                for cell in row.find_all(['th', 'td']):
                    stat = cell.get('data-stat')
                    value = cell.get_text(strip=True)
                    season_data[stat] = value
                
                if season_data:
                    totals_data.append(season_data)
            player_data['totals'] = totals_data
        
        advanced_table = soup.find('table', id='advanced')
        if advanced_table:
            advanced_data = []
            rows = advanced_table.find('tbody').find_all('tr')
            for row in rows:
                if row.get('class') and ('thead' in row.get('class') or 'over_header' in row.get('class')):
                    continue
                
                season_data = {}
                for cell in row.find_all(['th', 'td']):
                    stat = cell.get('data-stat')
                    value = cell.get_text(strip=True)
                    season_data[stat] = value
                
                if season_data:
                    advanced_data.append(season_data)
            player_data['advanced'] = advanced_data
        
        return player_data
    
    except Exception as e:
        print(f"获取球员数据失败: {e}")
        return None

def save_player_stats(player_id, player_name, player_data, output_dir='player_data'):
    """保存单个球员数据到JSON文件"""
    import json
    output_path = Path(output_dir) / 'players'
    output_path.mkdir(parents=True, exist_ok=True)
    
    player_data['player_id'] = player_id
    player_data['player_name'] = player_name
    
    safe_name = player_id or player_name.replace(' ', '_').replace('/', '_')
    output_file = output_path / f"{safe_name}.json"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(player_data, f, indent=2, ensure_ascii=False)
    
    return output_file

def main():
    print("=== Basketball Reference 球员数据爬取器 ===")
    print("1. 爬取球员列表")
    print("2. 爬取球员详细数据")
    print("3. 全部爬取")
    
    choice = input("请选择操作 (1/2/3): ").strip()
    
    if choice == '1' or choice == '3':
        print("\n开始爬取球员列表...")
        players = get_all_players()
        save_player_list(players)
        
        if choice == '1':
            return
    
    if choice == '2' or choice == '3':
        players_df = pd.read_csv('player_data/bbref_all_players.csv')
        print(f"\n开始爬取 {len(players_df)} 名球员的详细数据...")
        
        success_count = 0
        fail_count = 0
        
        for idx, row in tqdm(players_df.iterrows(), total=len(players_df), desc="爬取球员数据"):
            player_url = row['player_url']
            player_name = row['player_name']
            player_id = row['player_id']
            
            if pd.isna(player_url):
                fail_count += 1
                continue
            
            try:
                player_data = get_player_stats(player_url)
                if player_data:
                    save_player_stats(player_id, player_name, player_data)
                    success_count += 1
            except Exception as e:
                fail_count += 1
        
        print(f"\n爬取完成! 成功: {success_count}, 失败: {fail_count}")

if __name__ == "__main__":
    main()