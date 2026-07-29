#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA比赛数据存储模块 - 将赛程数据写入数据库
"""
import pandas as pd
import logging
import hashlib
from datetime import datetime
from typing import List, Dict, Any

from nba_data.data_importer.database import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GamesStorage:
    """比赛数据存储类"""

    def __init__(self, db_manager=None):
        """
        初始化存储类

        Args:
            db_manager: 数据库管理器实例
        """
        self.db = db_manager or DatabaseManager()

    def _generate_game_id(self, date_str: str, visitor: str, home: str) -> str:
        """
        生成唯一比赛ID

        Args:
            date_str: 比赛日期
            visitor: 客场球队
            home: 主场球队

        Returns:
            唯一比赛ID
        """
        unique_str = f"{date_str}_{visitor}_{home}"
        return hashlib.md5(unique_str.encode()).hexdigest()[:16]

    def _parse_game_data(self, row: pd.Series) -> Dict[str, Any]:
        """
        解析单行比赛数据

        Args:
            row: pandas Series 单行数据

        Returns:
            解析后的数据字典
        """
        # 提取日期
        date_str = str(row.get('Date', '')).strip()
        if not date_str:
            return None

        # 提取球队信息
        visitor_team = str(row.get('Visitor/Neutral', '')).strip()
        home_team = str(row.get('Home/Neutral', '')).strip()

        if not visitor_team or not home_team:
            return None

        # 提取比分
        try:
            visitor_score = int(row.get('VMP', 0)) if pd.notna(row.get('VMP')) else 0
            home_score = int(row.get('HMP', 0)) if pd.notna(row.get('HMP')) else 0
        except:
            visitor_score = 0
            home_score = 0

        # 判断胜负
        if visitor_score > home_score:
            visitor_result = 'W'
            home_result = 'L'
        elif visitor_score < home_score:
            visitor_result = 'L'
            home_result = 'W'
        else:
            visitor_result = 'T'
            home_result = 'T'

        # 提取加时赛标记
        ot_flag = ''
        if pd.notna(row.get('OT')):
            ot_str = str(row.get('OT', '')).strip()
            if 'OT' in ot_str:
                ot_flag = ot_str
            elif ot_str:
                ot_flag = f"{ot_str}OT"

        # 生成比赛ID
        game_id = self._generate_game_id(date_str, visitor_team, home_team)

        # 提取赛季信息
        season = str(row.get('Season', '')).strip()
        if not season and 'Year' in row:
            year = int(row.get('Year', 0))
            season = f"{year}-{year+1}"

        return {
            'game_id': game_id,
            'game_date': date_str,
            'season_id': season,
            'visitor_team': visitor_team,
            'home_team': home_team,
            'visitor_score': visitor_score,
            'home_score': home_score,
            'visitor_result': visitor_result,
            'home_result': home_result,
            'ot_flag': ot_flag,
            'attendance': str(row.get('Attendance', '')).strip() if pd.notna(row.get('Attendance')) else '',
            'notes': str(row.get('Notes/BoxScore', '')).strip() if pd.notna(row.get('Notes/BoxScore')) else ''
        }

    def save_schedule_to_database(self, df: pd.DataFrame, batch_size: int = 100) -> int:
        """
        将赛程数据保存到数据库

        Args:
            df: 包含赛程数据的DataFrame
            batch_size: 批量插入大小

        Returns:
            成功插入的记录数
        """
        if df.empty:
            logger.warning("没有数据需要保存")
            return 0

        logger.info(f"开始处理 {len(df)} 条比赛数据...")

        # 准备主队数据
        home_games = []
        # 准备客队数据
        visitor_games = []

        for _, row in df.iterrows():
            parsed = self._parse_game_data(row)
            if not parsed:
                continue

            # 主场数据
            home_games.append({
                'game_id': parsed['game_id'],
                'game_date': parsed['game_date'],
                'season_id': parsed['season_id'],
                'team_abbr': parsed['home_team'],
                'team_score': parsed['home_score'],
                'opp_score': parsed['visitor_score'],
                'result': parsed['home_result'],
                'is_home': True,
                'ot_flag': parsed['ot_flag'],
                'attendance': parsed['attendance']
            })

            # 客场数据
            visitor_games.append({
                'game_id': parsed['game_id'],
                'game_date': parsed['game_date'],
                'season_id': parsed['season_id'],
                'team_abbr': parsed['visitor_team'],
                'team_score': parsed['visitor_score'],
                'opp_score': parsed['home_score'],
                'result': parsed['visitor_result'],
                'is_home': False,
                'ot_flag': parsed['ot_flag'],
                'attendance': parsed['attendance']
            })

        # 合并数据
        all_games = home_games + visitor_games

        logger.info(f"解析完成，共 {len(all_games)} 条记录（主客场比赛）")

        # 插入数据库
        if self.db.table_exists('team_games'):
            # 使用 INSERT OR REPLACE
            query = """
                INSERT INTO team_games (
                    game_id, game_date, season_id, team_abbr,
                    team_score, opp_score, result, is_home, ot_flag, attendance
                ) VALUES (
                    %(game_id)s, %(game_date)s, %(season_id)s, %(team_abbr)s,
                    %(team_score)s, %(opp_score)s, %(result)s, %(is_home)s, %(ot_flag)s, %(attendance)s
                )
                ON CONFLICT (game_id, team_abbr) DO UPDATE SET
                    team_score = EXCLUDED.team_score,
                    opp_score = EXCLUDED.opp_score,
                    result = EXCLUDED.result,
                    ot_flag = EXCLUDED.ot_flag,
                    attendance = EXCLUDED.attendance
            """
        else:
            logger.error("表 team_games 不存在，请先创建数据库表")
            return 0

        # 执行批量插入
        inserted = 0
        errors = 0

        with self.db.get_cursor() as cursor:
            for i in range(0, len(all_games), batch_size):
                batch = all_games[i:i + batch_size]
                try:
                    cursor.executemany(query, batch)
                    inserted += len(batch)
                except Exception as e:
                    errors += len(batch)
                    logger.error(f"批量插入失败 (行 {i}-{i+len(batch)-1}): {e}")

        logger.info(f"✅ 成功插入/更新 {inserted} 条记录，跳过 {errors} 条错误记录")

        return inserted

    def load_from_csv(self, csv_path: str) -> pd.DataFrame:
        """
        从CSV文件加载数据

        Args:
            csv_path: CSV文件路径

        Returns:
            DataFrame
        """
        logger.info(f"从 {csv_path} 加载数据...")

        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
            logger.info(f"成功加载 {len(df)} 条记录")
            return df
        except Exception as e:
            logger.error(f"加载CSV文件失败: {e}")
            return pd.DataFrame()

    def process_and_save(self, csv_path: str, batch_size: int = 100) -> int:
        """
        从CSV文件处理并保存数据

        Args:
            csv_path: CSV文件路径
            batch_size: 批量插入大小

        Returns:
            成功插入的记录数
        """
        df = self.load_from_csv(csv_path)

        if df.empty:
            logger.warning("没有数据需要处理")
            return 0

        return self.save_schedule_to_database(df, batch_size)

if __name__ == "__main__":
    # 测试存储功能
    storage = GamesStorage()

    # 处理单个CSV文件
    csv_path = "nba_data/CSV/nba_full_schedule_2026.csv"
    if pd.read_csv(csv_path) if False else False:
        inserted = storage.process_and_save(csv_path)
        print(f"\n✅ 成功插入 {inserted} 条记录")
    else:
        print("测试数据文件不存在，请先运行爬虫抓取数据")
