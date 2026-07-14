#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basketball Reference 反爬机制处理工具
包含多种反爬策略：User-Agent轮换、随机延迟、指数退避等
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AntiCrawlConfig:
    """反爬配置类"""
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0"
    ]
    
    DEFAULT_DELAY = (3, 6)
    RATE_LIMIT_DELAY = (10, 15)
    MAX_RETRIES = 5
    BACKOFF_FACTOR = 2

class BasketballReferenceScraper:
    """带有反爬机制的Basketball Reference爬虫"""
    
    def __init__(self):
        self.session = requests.Session()
        self.config = AntiCrawlConfig()
        self._setup_session()
    
    def _setup_session(self):
        """配置会话，添加持久化连接和默认headers"""
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
    
    def _get_random_user_agent(self) -> str:
        """随机选择一个User-Agent"""
        return random.choice(self.config.USER_AGENTS)
    
    def _random_delay(self, delay_range: tuple = None):
        """随机延迟"""
        if delay_range is None:
            delay_range = self.config.DEFAULT_DELAY
        
        delay = random.uniform(*delay_range)
        logger.debug(f"等待 {delay:.2f} 秒")
        time.sleep(delay)
    
    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """带指数退避的重试机制"""
        last_exception = None
        
        for attempt in range(self.config.MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except requests.exceptions.RequestException as e:
                last_exception = e
                wait_time = self.config.BACKOFF_FACTOR ** attempt + random.uniform(0, 1)
                
                logger.warning(f"请求失败 ({attempt + 1}/{self.config.MAX_RETRIES}): {e}")
                logger.info(f"{wait_time:.2f}秒后重试...")
                
                time.sleep(wait_time)
        
        logger.error(f"达到最大重试次数，请求失败: {last_exception}")
        raise last_exception
    
    def _make_request(self, url: str, params: dict = None) -> requests.Response:
        """发送请求，包含反爬机制"""
        headers = {
            'User-Agent': self._get_random_user_agent()
        }
        
        self._random_delay()
        
        response = self._retry_with_backoff(
            self.session.get,
            url=url,
            headers=headers,
            params=params,
            timeout=30
        )
        
        if response.status_code == 429:
            logger.warning("触发速率限制，等待更长时间...")
            self._random_delay(self.config.RATE_LIMIT_DELAY)
            response = self._retry_with_backoff(
                self.session.get,
                url=url,
                headers=headers,
                params=params,
                timeout=30
            )
        
        response.raise_for_status()
        return response
    
    def get_player_list(self, letter: str) -> List[Dict[str, Any]]:
        """获取指定字母开头的球员列表"""
        url = f"https://www.basketball-reference.com/players/{letter.lower()}/"
        
        try:
            response = self._make_request(url)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            table = soup.find('table')
            if not table:
                logger.warning(f"字母 '{letter}' 未找到球员表")
                return []
            
            players = []
            for row in table.find_all('tr'):
                th = row.find('th', {'data-stat': 'player'})
                if th:
                    a_tag = th.find('a')
                    if a_tag and '/players/' in a_tag['href']:
                        player_name = a_tag.get_text(strip=True)
                        player_url = f"https://www.basketball-reference.com{a_tag['href']}"
                        player_id = player_url.split('/')[-1].replace('.html', '')
                        
                        from_year = row.find('td', {'data-stat': 'year_min'})
                        to_year = row.find('td', {'data-stat': 'year_max'})
                        position = row.find('td', {'data-stat': 'pos'})
                        height = row.find('td', {'data-stat': 'height'})
                        weight = row.find('td', {'data-stat': 'weight'})
                        
                        players.append({
                            'player_id': player_id,
                            'player_name': player_name,
                            'from_year': int(from_year.get_text()) if from_year else None,
                            'to_year': int(to_year.get_text()) if to_year else None,
                            'position': position.get_text() if position else None,
                            'height': height.get_text() if height else None,
                            'weight': int(weight.get_text()) if weight else None,
                            'player_url': player_url,
                            'is_active': not to_year or int(to_year.get_text()) >= 2025
                        })
            
            logger.info(f"字母 '{letter}' 获取到 {len(players)} 名球员")
            return players
        
        except Exception as e:
            logger.error(f"获取字母 '{letter}' 的球员失败: {e}")
            return []
    
    def get_all_players(self) -> pd.DataFrame:
        """获取所有球员数据"""
        all_players = []
        
        logger.info("开始爬取所有球员数据...")
        for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            players = self.get_player_list(letter)
            all_players.extend(players)
        
        logger.info(f"总共获取到 {len(all_players)} 名球员")
        return pd.DataFrame(all_players)
    
    def get_player_stats(self, player_url: str) -> Dict[str, Any]:
        """获取球员详细统计数据"""
        try:
            response = self._make_request(player_url)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            player_data = {}
            
            per_game_table = soup.find('table', id='per_game')
            if per_game_table:
                per_game_data = []
                for row in per_game_table.find('tbody').find_all('tr'):
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
            
            return player_data
        
        except Exception as e:
            logger.error(f"获取球员数据失败: {e}")
            return {}

def save_player_data(df: pd.DataFrame, output_dir: str = 'player_data'):
    """保存球员数据到CSV文件"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    df.to_csv(output_path / 'bbref_all_players.csv', index=False, encoding='utf-8-sig')
    logger.info(f"球员数据已保存到 {output_path / 'bbref_all_players.csv'}")

if __name__ == "__main__":
    scraper = BasketballReferenceScraper()
    players_df = scraper.get_all_players()
    save_player_data(players_df)
    
    print(f"\n✅ 爬取完成! 共获取 {len(players_df)} 名球员")