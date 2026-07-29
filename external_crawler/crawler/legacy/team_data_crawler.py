#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
球队数据爬虫 - 从 Basketball Reference 爬取球队比赛数据
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from base_scraper import BaseScraper
from bs4 import BeautifulSoup
import pandas as pd
import json
from pathlib import Path
import logging
import re
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('team_crawler.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class TeamDataCrawler(BaseScraper):
    """爬取球队数据的爬虫类"""

    BASE_URL = "https://www.basketball-reference.com/teams"
    SEASONS = ['2025-26', '2024-25', '2023-24', '2022-23']
    TEAM_ABBR = ['ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN',
                 'DET', 'GSW', 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA',
                 'MIL', 'MIN', 'NOP', 'NYK', 'OKC', 'ORL', 'PHI', 'PHX',
                 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS']

    def __init__(self):
        super().__init__(delay_min=3, delay_max=5)
        self.progress_file = Path(__file__).parent / 'crawler_progress.json'
        self.data_dir = Path(__file__).parent / 'crawler_data' / 'team_data'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"初始化 TeamDataCrawler，数据保存目录: {self.data_dir}")

    def get_team_season_url(self, team_abbr, season):
        """获取球队赛季数据页面URL

        Args:
            team_abbr: 球队缩写，如 'GSW'
            season: 赛季，如 '2024-25'

        Returns:
            str: 完整的URL
        """
        year = int(season.split('-')[1])
        url = f"{self.BASE_URL}/{team_abbr}/{year}.html"
        logger.debug(f"生成URL: {team_abbr} {season} -> {url}")
        return url

    def scrape_team_season_data(self, team_abbr, season):
        """爬取指定球队指定赛季的数据

        Args:
            team_abbr: 球队缩写
            season: 赛季

        Returns:
            pd.DataFrame: 包含比赛数据的DataFrame，失败返回None
        """
        url = self.get_team_season_url(team_abbr, season)
        logger.info(f"开始爬取: {team_abbr} {season}")

        try:
            response = self._retry_with_backoff(self._make_request, url)
            html_content = response.text
            logger.info(f"成功获取HTML，内容长度: {len(html_content)} 字符")

            df = self.parse_season_data(html_content, team_abbr, season)

            if df is not None and not df.empty:
                self.save_team_data(df, team_abbr, season)
                self.save_progress(team_abbr, season, status='completed')
                logger.info(f"✅ {team_abbr} {season} 爬取完成，共 {len(df)} 场比赛")
                return df
            else:
                logger.warning(f"⚠️ {team_abbr} {season} 无数据")
                self.save_progress(team_abbr, season, status='no_data')
                return None

        except Exception as e:
            logger.error(f"❌ {team_abbr} {season} 爬取失败: {e}")
            self.save_progress(team_abbr, season, status='failed')
            return None

    def parse_season_data(self, html_content, team_abbr, season):
        """解析赛季数据HTML，提取比赛信息

        Args:
            html_content: HTML内容字符串
            team_abbr: 球队缩写
            season: 赛季

        Returns:
            pd.DataFrame: 包含比赛数据的DataFrame
        """
        soup = BeautifulSoup(html_content, 'html.parser')

        games = []

        schedule_table = soup.find('table', {'id': 'schedule'})
        if not schedule_table:
            logger.warning(f"未找到比赛日程表 schedule")
            return pd.DataFrame()

        tbody = schedule_table.find('tbody')
        if not tbody:
            logger.warning(f"未找到 schedule 表体")
            return pd.DataFrame()

        rows = tbody.find_all('tr')
        logger.info(f"找到 {len(rows)} 行数据")

        for row in rows:
            try:
                game = self._parse_game_row(row, team_abbr, season)
                if game:
                    games.append(game)
            except Exception as e:
                logger.warning(f"解析比赛行失败: {e}")
                continue

        df = pd.DataFrame(games)

        if not df.empty:
            df = self._clean_and_validate(df)

        return df

    def _parse_game_row(self, row, team_abbr, season):
        """解析单行比赛数据

        Args:
            row: BeautifulSoup的tr元素
            team_abbr: 球队缩写
            season: 赛季

        Returns:
            dict: 比赛数据字典
        """
        cols = row.find_all(['th', 'td'])

        if len(cols) < 1:
            return None

        game = {
            'team_abbr': team_abbr,
            'season': season,
            'date': None,
            'game_id': None,
            'boxscore_url': None,
            'home_away': None,
            'opponent': None,
            'win_loss': None,
            'points_for': None,
            'points_against': None,
            'ot': None,
            'win_loss_record': None,
            'streak': None,
            'game_remarks': None
        }

        col_index = 0
        for col in cols:
            header = col.get('data-stat')
            value = col.get_text(strip=True)

            if header == 'date_game':
                try:
                    game['date'] = datetime.strptime(value, '%Y-%m-%d').strftime('%Y-%m-%d')
                except:
                    try:
                        game['date'] = datetime.strptime(value, '%b %d, %Y').strftime('%Y-%m-%d')
                    except:
                        game['date'] = value

                a_tag = col.find('a')
                if a_tag and a_tag.get('href'):
                    game['boxscore_url'] = 'https://www.basketball-reference.com' + a_tag['href']
                    match = re.search(r'/boxscores/(\d{8})', a_tag['href'])
                    if match:
                        game['game_id'] = match.group(1)

            elif header == 'boxscore_word':
                game['game_id'] = value

            elif header == 'home_away':
                game['home_away'] = 'home' if value == '' else 'away'

            elif header == 'opp_name':
                opponent_abbr = col.find('a')
                if opponent_abbr:
                    game['opponent'] = opponent_abbr.get('href', '').split('/')[-1].replace('.html', '').upper()
                else:
                    game['opponent'] = value

            elif header == 'wl':
                game['win_loss'] = value

            elif header == 'pts':
                try:
                    game['points_for'] = int(value)
                except:
                    pass

            elif header == 'opp_pts':
                try:
                    game['points_against'] = int(value)
                except:
                    pass

            elif header == 'ot':
                game['ot'] = value

            elif header == 'game_remarks':
                game['game_remarks'] = value if value else None

            col_index += 1

        if game['date'] and game['win_loss']:
            return game

        return None

    def _clean_and_validate(self, df):
        """清洗和验证数据

        Args:
            df: 原始DataFrame

        Returns:
            pd.DataFrame: 清洗后的DataFrame
        """
        required_cols = ['team_abbr', 'season', 'date', 'win_loss']
        for col in required_cols:
            if col not in df.columns:
                logger.warning(f"缺少必需列: {col}")
                return pd.DataFrame()

        df = df.dropna(subset=['team_abbr', 'season', 'date', 'win_loss'])

        df = df.reset_index(drop=True)

        return df

    def save_team_data(self, df, team_abbr, season):
        """保存球队数据到CSV文件

        Args:
            df: 比赛数据DataFrame
            team_abbr: 球队缩写
            season: 赛季
        """
        filename = f"{team_abbr}_{season.replace('-', '_')}_games.csv"
        filepath = self.data_dir / filename

        df.to_csv(filepath, index=False, encoding='utf-8')
        logger.info(f"数据已保存: {filepath}")

    def save_progress(self, team_abbr, season, status='completed'):
        """保存爬取进度

        Args:
            team_abbr: 球队缩写
            season: 赛季
            status: 状态 (completed, failed, no_data)
        """
        progress = self.load_progress()

        key = f"{team_abbr}_{season}"
        progress[key] = {
            'team_abbr': team_abbr,
            'season': season,
            'status': status,
            'updated_at': datetime.now().isoformat()
        }

        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

        logger.debug(f"进度已保存: {key} -> {status}")

    def load_progress(self):
        """加载爬取进度

        Returns:
            dict: 进度信息字典
        """
        if not self.progress_file.exists():
            return {}

        try:
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            logger.debug(f"已加载 {len(progress)} 条进度记录")
            return progress
        except Exception as e:
            logger.error(f"加载进度文件失败: {e}")
            return {}

    def is_already_completed(self, team_abbr, season):
        """检查是否已经完成爬取

        Args:
            team_abbr: 球队缩写
            season: 赛季

        Returns:
            bool: 是否已完成
        """
        progress = self.load_progress()
        key = f"{team_abbr}_{season}"
        return key in progress and progress[key].get('status') == 'completed'

    def scrape_all_recent_data(self, resume=True):
        """爬取所有球队最近4年数据

        Args:
            resume: 是否从断点继续，默认为True
        """
        logger.info("=" * 60)
        logger.info("开始爬取所有球队最近4年数据")
        logger.info(f"赛季列表: {self.SEASONS}")
        logger.info(f"球队数量: {len(self.TEAM_ABBR)}")
        logger.info("=" * 60)

        total_tasks = len(self.TEAM_ABBR) * len(self.SEASONS)
        completed_tasks = 0
        failed_tasks = 0
        skipped_tasks = 0

        progress = self.load_progress()
        for team_abbr in self.TEAM_ABBR:
            for season in self.SEASONS:
                key = f"{team_abbr}_{season}"

                if resume and key in progress:
                    status = progress[key].get('status')
                    if status == 'completed':
                        logger.info(f"跳过(已完成): {team_abbr} {season}")
                        skipped_tasks += 1
                        completed_tasks += 1
                        self._print_progress(completed_tasks, total_tasks, team_abbr, season, "跳过")
                        continue
                    elif status == 'no_data':
                        logger.info(f"跳过(无数据): {team_abbr} {season}")
                        skipped_tasks += 1
                        completed_tasks += 1
                        self._print_progress(completed_tasks, total_tasks, team_abbr, season, "跳过")
                        continue

                self._print_progress(completed_tasks + failed_tasks, total_tasks, team_abbr, season, "爬取中")

                result = self.scrape_team_season_data(team_abbr, season)

                if result is not None and not result.empty:
                    completed_tasks += 1
                else:
                    failed_tasks += 1

                self._print_progress(completed_tasks + failed_tasks, total_tasks, team_abbr, season, "完成")

        logger.info("=" * 60)
        logger.info("爬取任务完成")
        logger.info(f"总计: {total_tasks}, 完成: {completed_tasks}, 失败: {failed_tasks}, 跳过: {skipped_tasks}")
        logger.info("=" * 60)

        return {
            'total': total_tasks,
            'completed': completed_tasks,
            'failed': failed_tasks,
            'skipped': skipped_tasks
        }

    def _print_progress(self, current, total, team_abbr, season, status):
        """打印进度信息

        Args:
            current: 当前完成数
            total: 总任务数
            team_abbr: 当前球队
            season: 当前赛季
            status: 状态描述
        """
        percentage = (current / total) * 100 if total > 0 else 0
        bar_length = 30
        filled = int(bar_length * current / total) if total > 0 else 0
        bar = '█' * filled + '░' * (bar_length - filled)

        print(f"\r[{bar}] {percentage:6.2f}% ({current}/{total}) | {team_abbr} {season} | {status}  ", end='', flush=True)

    def get_team_stats(self, team_abbr, season):
        """获取球队赛季统计数据

        Args:
            team_abbr: 球队缩写
            season: 赛季

        Returns:
            dict: 球队统计数据
        """
        url = self.get_team_season_url(team_abbr, season)

        try:
            response = self._retry_with_backoff(self._make_request, url)
            soup = BeautifulSoup(response.text, 'html.parser')

            stats = {}

            stats_div = soup.find('div', {'id': 'all_team_stats'})
            if stats_div:
                table = stats_div.find('table', {'id': 'team_stats'})
                if table:
                    tbody = table.find('tbody')
                    if tbody:
                        row = tbody.find('tr')
                        if row:
                            cols = row.find_all(['th', 'td'])
                            for col in cols:
                                stat = col.get('data-stat')
                                value = col.get_text(strip=True)
                                if stat:
                                    stats[stat] = value

            return stats

        except Exception as e:
            logger.error(f"获取球队统计失败 {team_abbr} {season}: {e}")
            return {}


if __name__ == "__main__":
    print("=" * 60)
    print("🏀 NBA球队数据爬虫")
    print("=" * 60)

    crawler = TeamDataCrawler()

    print("\n📋 配置信息:")
    print(f"   - 请求延迟: {crawler.delay_min}-{crawler.delay_max}秒")
    print(f"   - 进度文件: {crawler.progress_file}")
    print(f"   - 数据目录: {crawler.data_dir}")

    print("\n📅 赛季列表:", ", ".join(crawler.SEASONS))
    print(f"🏀 球队数量: {len(crawler.TEAM_ABBR)}")

    print("\n" + "=" * 60)
    print("开始爬取...")
    print("=" * 60 + "\n")

    results = crawler.scrape_all_recent_data(resume=True)

    print("\n\n" + "=" * 60)
    print("📊 爬取结果汇总:")
    print(f"   总任务数: {results['total']}")
    print(f"   ✅ 完成: {results['completed']}")
    print(f"   ❌ 失败: {results['failed']}")
    print(f"   ⏭️ 跳过: {results['skipped']}")
    print("=" * 60)
