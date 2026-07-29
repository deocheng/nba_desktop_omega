#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Play by Play 和 Game Log 数据爬虫
从 Basketball Reference 爬取比赛详细数据
"""
import pandas as pd
import time
import logging
import os
import random
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from basketball_reference_web_scraper import client
    from basketball_reference_web_scraper.data import Team
    BBREF_AVAILABLE = True
except ImportError:
    BBREF_AVAILABLE = False
    logger.error("basketball_reference_web_scraper 未安装！")


class PlayByPlayScraper:
    """Play by Play 数据爬虫"""
    
    def __init__(self, headless=True, min_delay=40, max_delay=40):
        self.headless = headless
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.base_url = "https://www.basketball-reference.com"
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        self.incomplete_list = []
        self.incomplete_list_path = None
        self.start_time = None
        self.run_interval = 30 * 60  # 运行30分钟
        self.rest_interval = 5 * 60   # 休息5分钟
    
    def _safe_random_delay(self):
        """安全随机延迟，防止429错误"""
        delay = random.uniform(self.min_delay, self.max_delay)
        logger.info(f"休眠 {delay:.1f} 秒，防止触发网站的 429 请求过多限制...")
        time.sleep(delay)
    
    def _check_and_rest(self):
        """
        检查是否需要休息
        每运行30分钟，休息5分钟
        """
        if self.start_time is None:
            self.start_time = time.time()
            return
        
        elapsed = time.time() - self.start_time
        if elapsed >= self.run_interval:
            logger.info("=" * 80)
            logger.info(f"已运行 {elapsed/60:.1f} 分钟，休息 {self.rest_interval/60:.0f} 分钟...")
            logger.info("=" * 80)
            time.sleep(self.rest_interval)
            logger.info("休息结束，继续运行...")
            logger.info("=" * 80)
            self.start_time = time.time()  # 重置开始时间
    
    def _load_incomplete_list(self, output_dir, season_year):
        """加载未完成列表"""
        self.incomplete_list_path = os.path.join(output_dir, f"incomplete_pbp_{season_year}.json")
        if os.path.exists(self.incomplete_list_path):
            try:
                with open(self.incomplete_list_path, 'r', encoding='utf-8') as f:
                    self.incomplete_list = json.load(f)
                logger.info(f"加载未完成列表: {len(self.incomplete_list)} 个")
            except Exception as e:
                logger.warning(f"加载未完成列表失败: {e}")
                self.incomplete_list = []
        else:
            self.incomplete_list = []
    
    def _save_incomplete_list(self):
        """保存未完成列表"""
        if self.incomplete_list_path:
            try:
                with open(self.incomplete_list_path, 'w', encoding='utf-8') as f:
                    json.dump(self.incomplete_list, f, ensure_ascii=False, indent=2)
                logger.info(f"保存未完成列表: {len(self.incomplete_list)} 个")
            except Exception as e:
                logger.error(f"保存未完成列表失败: {e}")
    
    def _remove_from_incomplete_list(self, game_id):
        """从待完成列表中移除"""
        self.incomplete_list = [item for item in self.incomplete_list if item.get('game_id') != game_id]
        self._save_incomplete_list()
    
    def _add_to_incomplete_list(self, game_id, game_info, retry_count=0):
        """添加到待完成列表"""
        if not any(item.get('game_id') == game_id for item in self.incomplete_list):
            self.incomplete_list.append({
                'game_id': game_id,
                'game_info': game_info,
                'retry_count': retry_count
            })
            self._save_incomplete_list()
    
    def scrape_season_schedule(self, season_end_year):
        """
        获取赛季赛程
        """
        logger.info(f"获取 {season_end_year} 赛季赛程...")
        try:
            schedule = client.season_schedule(season_end_year=season_end_year)
            logger.info(f"成功获取 {len(schedule)} 场比赛")
            return schedule
        except Exception as e:
            logger.error(f"获取赛程失败: {e}")
            return []
    
    def scrape_season_games_page(self, season_end_year):
        """
        从 https://www.basketball-reference.com/leagues/NBA_2026_games.html 获取赛季赛程和boxscore链接
        
        Args:
            season_end_year: 赛季结束年份（如2026表示2025-2026赛季）
        
        Returns:
            包含比赛信息和boxscore链接的列表
        """
        url = f"{self.base_url}/leagues/NBA_{season_end_year}_games.html"
        logger.info(f"获取赛季赛程页面: {url}")
        
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()
                
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # 等待数据加载
                page.wait_for_timeout(3000)
                
                # 获取所有比赛行
                games_data = []
                
                # 查找包含月份标签的部分
                month_sections = page.query_selector_all('div#all_schedule > div')
                
                for section in month_sections:
                    # 获取月份标题
                    month_header = section.query_selector('h3')
                    month_name = month_header.inner_text().strip() if month_header else "Unknown"
                    
                    # 获取比赛表格
                    table = section.query_selector('table')
                    if not table:
                        continue
                    
                    rows = table.query_selector_all('tbody tr')
                    for row in rows:
                        try:
                            # 获取日期
                            date_cell = row.query_selector('td[data-stat="date_game"]')
                            if not date_cell:
                                continue
                            
                            date_str = date_cell.inner_text().strip()
                            
                            # 获取球队
                            visitor_cell = row.query_selector('td[data-stat="visitor_team_name"]')
                            home_cell = row.query_selector('td[data-stat="home_team_name"]')
                            
                            visitor_team = visitor_cell.inner_text().strip() if visitor_cell else ""
                            home_team = home_cell.inner_text().strip() if home_cell else ""
                            
                            # 获取比分
                            visitor_score_cell = row.query_selector('td[data-stat="visitor_pts"]')
                            home_score_cell = row.query_selector('td[data-stat="home_pts"]')
                            
                            visitor_score = visitor_score_cell.inner_text().strip() if visitor_score_cell else ""
                            home_score = home_score_cell.inner_text().strip() if home_score_cell else ""
                            
                            # 获取boxscore链接
                            boxscore_cell = row.query_selector('td[data-stat="box_score_text"] a')
                            boxscore_url = ""
                            if boxscore_cell:
                                href = boxscore_cell.get_attribute('href')
                                if href:
                                    boxscore_url = self.base_url + href
                            
                            # 获取比赛状态（是否进行中）
                            status_cell = row.query_selector('td[data-stat="game_status"]')
                            game_status = status_cell.inner_text().strip() if status_cell else ""
                            
                            games_data.append({
                                'month': month_name,
                                'date': date_str,
                                'visitor_team': visitor_team,
                                'home_team': home_team,
                                'visitor_score': visitor_score,
                                'home_score': home_score,
                                'boxscore_url': boxscore_url,
                                'status': game_status
                            })
                            
                        except Exception as e:
                            logger.warning(f"解析比赛行失败: {e}")
                            continue
                
                browser.close()
                logger.info(f"✅ 成功获取 {len(games_data)} 场比赛")
                return games_data
                
        except Exception as e:
            logger.error(f"❌ 获取赛季赛程页面失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def scrape_month_games(self, season_end_year, month_name):
        """
        从 https://www.basketball-reference.com/leagues/NBA_2026_games-october.html 等月份页面获取数据
        
        Args:
            season_end_year: 赛季结束年份（如2026表示2025-2026赛季）
            month_name: 月份名称（如 'october', 'november' 等）
        
        Returns:
            包含比赛信息和boxscore链接的列表（只包含有boxscore的比赛）
        """
        url = f"{self.base_url}/leagues/NBA_{season_end_year}_games-{month_name}.html"
        logger.info(f"获取月份赛程页面: {url}")
        
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()
                
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # 等待数据加载
                page.wait_for_timeout(3000)
                
                # 获取所有比赛行（只获取有boxscore的比赛）
                games_with_boxscore = []
                
                # 查找比赛表格
                table = page.query_selector('table#schedule')
                if not table:
                    logger.warning("未找到比赛表格")
                    browser.close()
                    return []
                
                rows = table.query_selector_all('tbody tr')
                for row in rows:
                    try:
                        # 获取boxscore链接（只处理有boxscore的比赛）
                        boxscore_cell = row.query_selector('td[data-stat="box_score_text"] a')
                        if not boxscore_cell:
                            continue  # 跳过没有boxscore的比赛
                            
                        href = boxscore_cell.get_attribute('href')
                        boxscore_url = self.base_url + href if href else ""
                        if not boxscore_url:
                            continue
                        
                        # 获取日期
                        date_cell = row.query_selector('td[data-stat="date_game"]')
                        date_str = date_cell.inner_text().strip() if date_cell else ""
                        
                        # 获取球队
                        visitor_cell = row.query_selector('td[data-stat="visitor_team_name"]')
                        home_cell = row.query_selector('td[data-stat="home_team_name"]')
                        
                        visitor_team = visitor_cell.inner_text().strip() if visitor_cell else ""
                        home_team = home_cell.inner_text().strip() if home_cell else ""
                        
                        # 获取比分
                        visitor_score_cell = row.query_selector('td[data-stat="visitor_pts"]')
                        home_score_cell = row.query_selector('td[data-stat="home_pts"]')
                        
                        visitor_score = visitor_score_cell.inner_text().strip() if visitor_score_cell else ""
                        home_score = home_score_cell.inner_text().strip() if home_score_cell else ""
                        
                        games_with_boxscore.append({
                            'month': month_name,
                            'date': date_str,
                            'visitor_team': visitor_team,
                            'home_team': home_team,
                            'visitor_score': visitor_score,
                            'home_score': home_score,
                            'boxscore_url': boxscore_url
                        })
                        
                    except Exception as e:
                        logger.warning(f"解析比赛行失败: {e}")
                        continue
                
                browser.close()
                logger.info(f"✅ {month_name}月: 找到 {len(games_with_boxscore)} 场有boxscore的比赛")
                return games_with_boxscore
                
        except Exception as e:
            logger.error(f"❌ 获取 {month_name} 月赛程页面失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def scrape_season_all_months(self, season_end_year, months=None):
        """
        爬取整个赛季所有月份的数据（只获取有boxscore的比赛）
        
        Args:
            season_end_year: 赛季结束年份（如2026表示2025-2026赛季）
            months: 要爬取的月份列表，默认全部月份
        
        Returns:
            所有有boxscore的比赛数据列表
        """
        # NBA赛季月份顺序（10月到次年6月）
        default_months = ['october', 'november', 'december', 'january', 'february', 'march', 'april', 'may', 'june']
        target_months = months or default_months
        
        all_games = []
        
        for month_name in target_months:
            logger.info(f"\n" + "=" * 80)
            logger.info(f"处理 {month_name} 月...")
            logger.info("=" * 80)
            
            # 获取该月份有boxscore的比赛
            games = self.scrape_month_games(season_end_year, month_name)
            all_games.extend(games)
            
            # 检查是否需要休息
            self._check_and_rest()
            
            # 防封锁延迟（不是最后一个月份）
            if month_name != target_months[-1]:
                self._safe_random_delay()
        
        logger.info(f"\n" + "=" * 80)
        logger.info(f"✅ 赛季爬取完成，共获取 {len(all_games)} 场有boxscore的比赛")
        logger.info("=" * 80)
        
        return all_games
    
    def scrape_daily_boxscores(self, year, month, day):
        """
        从 https://www.basketball-reference.com/boxscores/ 获取每日的 box scores 数据
        
        Args:
            year: 年份
            month: 月份 (1-12)
            day: 日期 (1-31)
        
        Returns:
            当日所有比赛的 box scores 数据
        """
        url = f"{self.base_url}/boxscores/?month={month}&day={day}&year={year}"
        logger.info(f"获取 boxscores: {url}")
        
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()
                
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # 等待数据加载
                page.wait_for_timeout(2000)
                
                # 获取所有比赛链接
                game_links = page.query_selector_all('a[href*="/boxscores/20"]')
                logger.info(f"找到 {len(game_links)} 场比赛")
                
                games_data = []
                for link in game_links:
                    href = link.get_attribute('href')
                    if href and '/boxscores/' in href:
                        game_url = self.base_url + href
                        logger.info(f"处理比赛: {game_url}")
                        
                        # 获取比赛日期
                        date_str = href.split('/')[3].split('.')[0]
                        date_obj = datetime.strptime(date_str, '%Y%m%d')
                        
                        # 获取球队信息
                        team_text = link.inner_text().strip()
                        teams = team_text.split(' @ ') if '@' in team_text else team_text.split(' vs ')
                        
                        games_data.append({
                            'url': game_url,
                            'date': date_obj,
                            'teams': teams,
                            'date_str': date_str
                        })
                
                browser.close()
                logger.info(f"✅ 成功获取 {len(games_data)} 场比赛信息")
                return games_data
                
        except Exception as e:
            logger.error(f"❌ 获取 boxscores 失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def scrape_single_boxscore(self, game_url):
        """
        获取单场比赛的详细 boxscore 数据
        
        Args:
            game_url: 比赛的 boxscore URL
        
        Returns:
            包含球员统计、球队统计的字典
        """
        logger.info(f"获取详细 boxscore: {game_url}")
        
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()
                
                page.goto(game_url, wait_until="domcontentloaded", timeout=30000)
                
                # 等待数据加载
                page.wait_for_timeout(3000)
                
                # 获取比赛基本信息
                game_info = {}
                
                # 获取球队名称
                team_names = page.query_selector_all('.scorebox div:not(.scorebox_meta) a')
                if len(team_names) >= 2:
                    game_info['away_team'] = team_names[0].inner_text().strip()
                    game_info['home_team'] = team_names[1].inner_text().strip()
                
                # 获取比分
                scores = page.query_selector_all('.scorebox .score')
                if len(scores) >= 2:
                    game_info['away_score'] = int(scores[0].inner_text().strip())
                    game_info['home_score'] = int(scores[1].inner_text().strip())
                
                # 获取球员统计数据
                player_stats = []
                tables = page.query_selector_all('table[id*="_basic"]')
                
                for table in tables:
                    table_id = table.get_attribute('id')
                    team_abbr = table_id.split('_')[0] if table_id else 'unknown'
                    
                    headers = []
                    th_elements = table.query_selector_all('thead th')
                    for th in th_elements:
                        headers.append(th.inner_text().strip())
                    
                    rows = table.query_selector_all('tbody tr')
                    for row in rows:
                        cells = row.query_selector_all('td')
                        player_data = {'team': team_abbr}
                        for i, cell in enumerate(cells):
                            if i < len(headers):
                                player_data[headers[i]] = cell.inner_text().strip()
                        if player_data.get('Player') and player_data['Player'] != 'Team Totals':
                            player_stats.append(player_data)
                
                game_info['player_stats'] = player_stats
                game_info['url'] = game_url
                
                browser.close()
                logger.info(f"✅ 成功获取 {len(player_stats)} 名球员数据")
                return game_info
                
        except Exception as e:
            logger.error(f"❌ 获取 boxscore 失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def scrape_play_by_play_data(self, game_url):
        """
        从 boxscore URL 提取 play-by-play 数据
        
        URL格式: https://www.basketball-reference.com/boxscores/202606030SAS.html
        PBP URL: https://www.basketball-reference.com/boxscores/pbp/202606030SAS.html
        
        Args:
            game_url: 比赛的 boxscore URL
        
        Returns:
            play-by-play 数据列表
        """
        # 构建 play-by-play URL
        if '/boxscores/' in game_url and '/pbp/' not in game_url:
            pbp_url = game_url.replace('/boxscores/', '/boxscores/pbp/')
        else:
            pbp_url = game_url
        
        logger.info(f"获取 play-by-play 数据: {pbp_url}")
        
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()
                
                page.goto(pbp_url, wait_until="domcontentloaded", timeout=30000)
                
                # 等待数据加载
                page.wait_for_timeout(3000)
                
                # 获取 play-by-play 数据
                pbp_data = []
                
                # 查找 play-by-play 表格
                table = page.query_selector('table#pbp')
                if not table:
                    logger.warning("未找到 play-by-play 表格")
                    browser.close()
                    return []
                
                rows = table.query_selector_all('tbody tr')
                for row in rows:
                    try:
                        # 获取节次和时间
                        period_cell = row.query_selector('td[data-stat="period"]')
                        time_cell = row.query_selector('td[data-stat="game_clock"]')
                        
                        period = period_cell.inner_text().strip() if period_cell else ""
                        game_clock = time_cell.inner_text().strip() if time_cell else ""
                        
                        # 获取客队动作
                        visitor_action = row.query_selector('td[data-stat="visitor_actions"]')
                        visitor_text = visitor_action.inner_text().strip() if visitor_action else ""
                        
                        # 获取主队动作
                        home_action = row.query_selector('td[data-stat="home_actions"]')
                        home_text = home_action.inner_text().strip() if home_action else ""
                        
                        # 获取比分
                        visitor_score_cell = row.query_selector('td[data-stat="visitor_score"]')
                        home_score_cell = row.query_selector('td[data-stat="home_score"]')
                        
                        visitor_score = visitor_score_cell.inner_text().strip() if visitor_score_cell else ""
                        home_score = home_score_cell.inner_text().strip() if home_score_cell else ""
                        
                        pbp_data.append({
                            'period': period,
                            'game_clock': game_clock,
                            'visitor_action': visitor_text,
                            'home_action': home_text,
                            'visitor_score': visitor_score,
                            'home_score': home_score
                        })
                        
                    except Exception as e:
                        logger.warning(f"解析 play-by-play 行失败: {e}")
                        continue
                
                browser.close()
                logger.info(f"✅ 成功获取 {len(pbp_data)} 条 play-by-play 记录")
                return pbp_data
                
        except Exception as e:
            logger.error(f"❌ 获取 play-by-play 失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def scrape_play_by_play(self, game_info):
        """
        获取单场比赛的 play by play 数据
        
        game_info格式: {'home_team': Team, 'away_team': Team, 'date': datetime}
        """
        try:
            date_obj = game_info['date']
            home_team = game_info['home_team']
            away_team = game_info['away_team']
            
            game_id = f"{away_team.value}_{home_team.value}_{date_obj.strftime('%Y%m%d')}"
            logger.info(f"获取比赛 {game_id} 的 play by play 数据...")
            
            play_by_play_data = client.play_by_play(
                home_team=home_team,
                day=date_obj.day,
                month=date_obj.month,
                year=date_obj.year
            )
            
            logger.info(f"✅ 成功获取 {len(play_by_play_data)} 条 play by play 记录")
            return play_by_play_data, game_id
            
        except Exception as e:
            logger.error(f"❌ 获取 play by play 失败: {e}")
            return None, None
    
    def scrape_box_scores(self, game_info):
        """
        获取单场比赛的 box scores 数据
        """
        try:
            date_obj = game_info['date']
            
            logger.info(f"获取比赛的 box scores 数据...")
            
            player_box_scores = client.player_box_scores(
                day=date_obj.day,
                month=date_obj.month,
                year=date_obj.year
            )
            
            team_box_scores = client.team_box_scores(
                day=date_obj.day,
                month=date_obj.month,
                year=date_obj.year
            )
            
            logger.info(f"✅ 成功获取 {len(player_box_scores)} 条球员数据，{len(team_box_scores)} 条球队数据")
            return player_box_scores, team_box_scores
            
        except Exception as e:
            logger.error(f"❌ 获取 box scores 失败: {e}")
            return None, None
    
    def save_play_by_play_to_csv(self, play_by_play_data, game_id, output_dir):
        """保存 play by play 数据到 CSV"""
        if not play_by_play_data:
            return
        
        os.makedirs(output_dir, exist_ok=True)
        filename = f"pbp_{game_id}.csv"
        filepath = os.path.join(output_dir, filename)
        
        try:
            df = pd.DataFrame(play_by_play_data)
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
            logger.info(f"✓ 已保存: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"保存失败: {e}")
            return None
    
    def save_box_scores_to_csv(self, player_box_scores, team_box_scores, game_id, output_dir):
        """保存 box scores 数据到 CSV"""
        os.makedirs(output_dir, exist_ok=True)
        
        player_file = os.path.join(output_dir, f"player_box_{game_id}.csv")
        team_file = os.path.join(output_dir, f"team_box_{game_id}.csv")
        
        try:
            if player_box_scores:
                pd.DataFrame(player_box_scores).to_csv(player_file, index=False, encoding='utf-8-sig')
                logger.info(f"✓ 已保存球员数据: {player_file}")
            
            if team_box_scores:
                pd.DataFrame(team_box_scores).to_csv(team_file, index=False, encoding='utf-8-sig')
                logger.info(f"✓ 已保存球队数据: {team_file}")
                
        except Exception as e:
            logger.error(f"保存失败: {e}")
    
    def scrape_season_play_by_play(self, season_end_year, output_dir=None, max_games=None):
        """
        抓取整个赛季的 play by play 和 box scores 数据
        """
        output_dir = output_dir or "nba_data/CSV/play_by_play"
        
        logger.info("=" * 80)
        logger.info(f"开始抓取 {season_end_year} 赛季 play by play 数据")
        logger.info("=" * 80)
        
        # 获取赛程
        schedule = self.scrape_season_schedule(season_end_year)
        if not schedule:
            logger.error("没有获取到赛程数据")
            return
        
        # 加载未完成列表
        self._load_incomplete_list(output_dir, season_end_year)
        
        all_results = []
        processed_count = 0
        
        for game_info in schedule:
            if max_games and processed_count >= max_games:
                logger.info(f"已达到最大抓取数量 {max_games}")
                break
            
            date_obj = game_info['date']
            home_team = game_info['home_team']
            away_team = game_info['away_team']
            game_id = f"{away_team.value}_{home_team.value}_{date_obj.strftime('%Y%m%d')}"
            
            # 检查是否已存在
            if output_dir:
                player_box_file = os.path.join(output_dir, f"player_box_{game_id}.csv")
                if os.path.exists(player_box_file):
                    logger.info(f"文件已存在，跳过: {game_id}")
                    processed_count += 1
                    continue
            
            logger.info(f"\n处理比赛 {processed_count + 1}/{len(schedule)}")
            logger.info(f"  时间: {date_obj.strftime('%Y-%m-%d')}")
            logger.info(f"  对阵: {away_team.value} @ {home_team.value}")
            
            # 获取 play by play
            pbp_data, pbp_id = self.scrape_play_by_play(game_info)
            
            # 获取 box scores
            player_box_data, team_box_data = self.scrape_box_scores(game_info)
            
            if pbp_data and player_box_data and team_box_data:
                # 保存数据
                if output_dir:
                    self.save_play_by_play_to_csv(pbp_data, game_id, output_dir)
                    self.save_box_scores_to_csv(player_box_data, team_box_data, game_id, output_dir)
                
                all_results.append({
                    'game_id': game_id,
                    'game_info': game_info,
                    'play_by_play_count': len(pbp_data),
                    'player_box_count': len(player_box_data),
                    'team_box_count': len(team_box_data)
                })
                
                # 从未完成列表移除
                self._remove_from_incomplete_list(game_id)
            else:
                # 添加到未完成列表
                self._add_to_incomplete_list(game_id, {
                    'date': date_obj.strftime('%Y-%m-%d'),
                    'home_team': home_team.value,
                    'away_team': away_team.value
                })
            
            processed_count += 1
            
            # 检查是否需要休息
            self._check_and_rest()
            
            # 防封锁延迟（不是最后一个）
            if processed_count < len(schedule) and (not max_games or processed_count < max_games):
                self._safe_random_delay()
        
        logger.info("\n" + "=" * 80)
        logger.info(f"✅ 抓取完成，成功 {len(all_results)} 场，未完成 {len(self.incomplete_list)} 场")
        logger.info("=" * 80)
        
        return all_results


if __name__ == "__main__":
    # 测试：抓取2024-2025赛季的部分数据
    scraper = PlayByPlayScraper(headless=True)
    
    # 先试试获取赛程
    schedule = scraper.scrape_season_schedule(2025)
    if schedule:
        logger.info(f"获取到 {len(schedule)} 场比赛")
        logger.info(f"前5场:")
        for game in schedule[:5]:
            logger.info(f"  {game['date'].strftime('%Y-%m-%d')}: {game['away_team'].value} @ {game['home_team'].value}")
    else:
        logger.warning("未获取到赛程数据")
