#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA API客户端 - 用于从NBA官方API获取数据
"""
from nba_api.stats.endpoints import (
    leaguedashteamstats,
    leaguedashplayerstats,
    playergamelog,
    teamgamelog,
    boxscoretraditionalv2,
    playbyplayv3,
    scoreboardv2,
    leaguestandingsv3
)
import time
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NBAPIClient:
    """NBA API客户端类"""
    
    def __init__(self, max_retries=3, base_delay=2):
        """
        初始化NBA API客户端
        
        Args:
            max_retries: 最大重试次数
            base_delay: 基础延迟时间（秒）
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    def _retry_with_backoff(self, func, *args, **kwargs):
        """
        带指数退避的重试机制
        
        Args:
            func: 要执行的函数
            *args: 函数参数
            **kwargs: 函数关键字参数
            
        Returns:
            函数执行结果
        """
        for retry in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"尝试 {retry+1}/{self.max_retries} 失败: {e}")
                if retry < self.max_retries - 1:
                    delay = self.base_delay * (2 ** retry)
                    logger.info(f"{delay}秒后重试...")
                    time.sleep(delay)
                else:
                    logger.error(f"达到最大重试次数，操作失败: {e}")
                    raise
    
    def get_team_stats(self, team_id, season, per_mode='PerGame'):
        """
        获取球队赛季统计数据
        
        Args:
            team_id: 球队ID
            season: 赛季，如 '2023-24'
            per_mode: 统计模式，如 'PerGame', 'Totals'
            
        Returns:
            球队统计数据
        """
        def _get_stats():
            team_stats = leaguedashteamstats.LeagueDashTeamStats(
                season=season,
                team_id_nullable=team_id,
                per_mode_detailed=per_mode
            )
            return team_stats.get_data_frames()[0]
        
        return self._retry_with_backoff(_get_stats)
    
    def get_player_stats(self, player_id, season, per_mode='PerGame'):
        """
        获取球员赛季统计数据
        
        Args:
            player_id: 球员ID
            season: 赛季，如 '2023-24'
            per_mode: 统计模式，如 'PerGame', 'Totals'
            
        Returns:
            球员统计数据
        """
        def _get_stats():
            player_stats = leaguedashplayerstats.LeagueDashPlayerStats(
                season=season,
                player_id_nullable=player_id,
                per_mode_detailed=per_mode
            )
            return player_stats.get_data_frames()[0]
        
        return self._retry_with_backoff(_get_stats)
    
    def get_player_gamelog(self, player_id, season):
        """
        获取球员比赛日志
        
        Args:
            player_id: 球员ID
            season: 赛季，如 '2023-24'
            
        Returns:
            球员比赛日志数据
        """
        def _get_gamelog():
            gamelog = playergamelog.PlayerGameLog(
                player_id=player_id,
                season=season
            )
            return gamelog.get_data_frames()[0]
        
        return self._retry_with_backoff(_get_gamelog)
    
    def get_team_gamelog(self, team_id, season):
        """
        获取球队比赛日志
        
        Args:
            team_id: 球队ID
            season: 赛季，如 '2023-24'
            
        Returns:
            球队比赛日志数据
        """
        def _get_gamelog():
            gamelog = teamgamelog.TeamGameLog(
                team_id=team_id,
                season=season
            )
            return gamelog.get_data_frames()[0]
        
        return self._retry_with_backoff(_get_gamelog)
    
    def get_boxscore(self, game_id):
        """
        获取比赛技术统计
        
        Args:
            game_id: 比赛ID
            
        Returns:
            比赛技术统计数据
        """
        def _get_boxscore():
            boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(
                game_id=game_id
            )
            return boxscore.get_data_frames()
        
        return self._retry_with_backoff(_get_boxscore)
    
    def get_playbyplay(self, game_id):
        """
        获取比赛play-by-play数据
        
        Args:
            game_id: 比赛ID
            
        Returns:
            比赛play-by-play数据
        """
        def _get_playbyplay():
            pbp = playbyplayv3.PlayByPlayV3(
                game_id=game_id
            )
            return pbp.get_data_frames()[0]
        
        return self._retry_with_backoff(_get_playbyplay)
    
    def get_scoreboard(self, game_date):
        """
        获取指定日期的比赛信息
        
        Args:
            game_date: 比赛日期，如 '2023-12-25'
            
        Returns:
            比赛信息数据
        """
        def _get_scoreboard():
            scoreboard = scoreboardv2.ScoreboardV2(
                game_date=game_date
            )
            return scoreboard.get_data_frames()
        
        return self._retry_with_backoff(_get_scoreboard)
    
    def get_standings(self, season):
        """
        获取赛季排名
        
        Args:
            season: 赛季，如 '2023-24'
            
        Returns:
            赛季排名数据
        """
        def _get_standings():
            standings = leaguestandingsv3.LeagueStandingsV3(
                season=season
            )
            return standings.get_data_frames()[0]
        
        return self._retry_with_backoff(_get_standings)

if __name__ == "__main__":
    # 测试NBA API客户端
    client = NBAPIClient()
    
    # 测试获取球队统计数据
    try:
        # 测试获取湖人(1610612747)的2023-24赛季数据
        team_stats = client.get_team_stats('1610612747', '2023-24')
        print("球队统计数据获取成功:")
        print(team_stats.head())
    except Exception as e:
        print(f"测试失败: {e}")