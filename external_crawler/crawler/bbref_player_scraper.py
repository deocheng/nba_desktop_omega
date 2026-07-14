#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basketball Reference球员数据爬取器
用于从https://www.basketball-reference.com/players/爬取所有NBA球员数据
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import logging
import os
from pathlib import Path
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright 未安装，将仅使用 requests 模式")

class BBRefPlayerScraper:
    """Basketball Reference球员数据爬取器"""
    
    def __init__(self, max_retries=3, base_delay=3, use_playwright=False, headless=True):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.base_url = "https://www.basketball-reference.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE
        self.headless = headless
    
    def _random_delay(self):
        """随机延迟，避免被封锁"""
        delay = self.base_delay + random.uniform(1, 3)
        time.sleep(delay)
    
    def _retry_with_backoff(self, func, *args, **kwargs):
        """带指数退避的重试机制"""
        for retry in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"尝试 {retry+1}/{self.max_retries} 失败: {e}")
                if retry < self.max_retries - 1:
                    delay = self.base_delay * (2 ** retry) + random.uniform(0, 2)
                    logger.info(f"{delay:.1f}秒后重试...")
                    time.sleep(delay)
                else:
                    logger.error(f"达到最大重试次数，操作失败: {e}")
                    raise
    
    def _get_soup(self, url):
        """获取页面的BeautifulSoup对象"""
        def _fetch():
            self._random_delay()
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        
        return self._retry_with_backoff(_fetch)
    
    def get_player_list_by_letter(self, letter):
        """获取指定字母开头的球员列表"""
        url = f"{self.base_url}/players/{letter.lower()}/"
        logger.info(f"获取字母 '{letter}' 开头的球员列表")
        
        soup = self._get_soup(url)
        table = soup.find('table', id=f'players_{letter.lower()}')
        
        if not table:
            logger.warning(f"未找到字母 '{letter}' 的球员表")
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
                player_url = self.base_url + player_link['href']
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
        
        logger.info(f"字母 '{letter}' 找到 {len(players)} 名球员")
        return players
    
    def get_all_players(self):
        """获取所有字母开头的球员列表"""
        letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        all_players = []
        
        for letter in letters:
            try:
                players = self.get_player_list_by_letter(letter)
                all_players.extend(players)
            except Exception as e:
                logger.error(f"获取字母 '{letter}' 的球员列表失败: {e}")
        
        logger.info(f"总共找到 {len(all_players)} 名球员")
        return all_players
    
    def get_player_stats(self, player_url, season=None):
        """获取球员详细统计数据"""
        logger.info(f"获取球员数据: {player_url}")
        
        soup = self._get_soup(player_url)
        
        player_data = {}
        
        meta_div = soup.find('div', id='meta')
        if meta_div:
            name_tag = meta_div.find('h1', itemprop='name')
            if name_tag:
                player_data['name'] = name_tag.get_text(strip=True)
            
            position_tag = meta_div.find('strong', string='Position:')
            if position_tag:
                player_data['position'] = position_tag.next_sibling.strip()
            
            height_tag = meta_div.find('span', itemprop='height')
            if height_tag:
                player_data['height'] = height_tag.get_text(strip=True)
            
            weight_tag = meta_div.find('span', itemprop='weight')
            if weight_tag:
                player_data['weight'] = weight_tag.get_text(strip=True)
            
            birth_date_tag = meta_div.find('span', itemprop='birthDate')
            if birth_date_tag:
                player_data['birth_date'] = birth_date_tag.get_text(strip=True)
            
            college_tag = meta_div.find('a', href=True)
            if college_tag and '/colleges/' in college_tag['href']:
                player_data['college'] = college_tag.get_text(strip=True)
        
        per_game_table = soup.find('table', id='per_game')
        if per_game_table:
            per_game_data = []
            rows = per_game_table.find('tbody').find_all('tr')
            for row in rows:
                if row.get('class') and 'thead' in row.get('class'):
                    continue
                
                season_data = {}
                for cell in row.find_all(['th', 'td']):
                    stat = cell.get('data-stat')
                    value = cell.get_text(strip=True)
                    season_data[stat] = value
                
                per_game_data.append(season_data)
            player_data['per_game'] = per_game_data
        
        totals_table = soup.find('table', id='totals')
        if totals_table:
            totals_data = []
            rows = totals_table.find('tbody').find_all('tr')
            for row in rows:
                if row.get('class') and 'thead' in row.get('class'):
                    continue
                
                season_data = {}
                for cell in row.find_all(['th', 'td']):
                    stat = cell.get('data-stat')
                    value = cell.get_text(strip=True)
                    season_data[stat] = value
                
                totals_data.append(season_data)
            player_data['totals'] = totals_data
        
        advanced_table = soup.find('table', id='advanced')
        if advanced_table:
            advanced_data = []
            rows = advanced_table.find('tbody').find_all('tr')
            for row in rows:
                if row.get('class') and 'thead' in row.get('class'):
                    continue
                
                season_data = {}
                for cell in row.find_all(['th', 'td']):
                    stat = cell.get('data-stat')
                    value = cell.get_text(strip=True)
                    season_data[stat] = value
                
                advanced_data.append(season_data)
            player_data['advanced'] = advanced_data
        
        return player_data
    
    def save_player_list(self, players, output_dir='player_data'):
        """保存球员列表到CSV文件"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        df = pd.DataFrame(players)
        output_file = output_path / 'bbref_all_players.csv'
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        logger.info(f"球员列表已保存到: {output_file}")
        
        return output_file
    
    def save_player_stats(self, player_data, output_dir='player_data'):
        """保存单个球员数据到JSON文件"""
        import json
        output_path = Path(output_dir) / 'players'
        output_path.mkdir(parents=True, exist_ok=True)
        
        player_id = player_data.get('player_id') or player_data.get('name', 'unknown').replace(' ', '_')
        output_file = output_path / f"{player_id}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(player_data, f, indent=2, ensure_ascii=False)
        
        return output_file

def main():
    scraper = BBRefPlayerScraper(base_delay=3)
    
    print("=== Basketball Reference 球员数据爬取器 ===")
    print("1. 爬取球员列表")
    print("2. 爬取球员详细数据")
    print("3. 全部爬取")
    
    choice = input("请选择操作 (1/2/3): ").strip()
    
    if choice == '1' or choice == '3':
        print("开始爬取球员列表...")
        players = scraper.get_all_players()
        scraper.save_player_list(players)
        
        if choice == '1':
            print(f"已爬取 {len(players)} 名球员")
            return
    
    if choice == '2' or choice == '3':
        players_df = pd.read_csv('player_data/bbref_all_players.csv')
        print(f"开始爬取 {len(players_df)} 名球员的详细数据...")
        
        success_count = 0
        fail_count = 0
        
        for idx, row in players_df.iterrows():
            player_url = row['player_url']
            player_name = row['player_name']
            
            try:
                player_data = scraper.get_player_stats(player_url)
                player_data['player_id'] = row['player_id']
                player_data['player_name'] = player_name
                scraper.save_player_stats(player_data)
                success_count += 1
                print(f"[{idx+1}/{len(players_df)}] 成功: {player_name}")
            except Exception as e:
                fail_count += 1
                print(f"[{idx+1}/{len(players_df)}] 失败: {player_name} - {e}")
        
        print(f"\n爬取完成! 成功: {success_count}, 失败: {fail_count}")

if __name__ == "__main__":
    main()