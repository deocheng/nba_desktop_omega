#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源选择器 - 用于根据环境和需求选择合适的数据源
"""
import os
import platform
import logging
from .nba_api_client import NBAPIClient
from .bbref_scraper import BasketballReferenceScraper

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataSourceSelector:
    """数据源选择器类"""
    
    def __init__(self):
        """
        初始化数据源选择器
        """
        self.nba_api_client = NBAPIClient()
        self.bbref_scraper = BasketballReferenceScraper()
        self._detect_environment()
    
    def _detect_environment(self):
        """
        检测运行环境
        """
        self.environment = "local"
        
        # 检测是否在云环境中运行
        if os.environ.get('CLOUD_ENV') or os.environ.get('AWS_REGION') or os.environ.get('AZURE_REGION'):
            self.environment = "cloud"
        
        # 检测IP地址是否可能被NBA API封禁
        # 这里可以添加更复杂的IP检测逻辑
        
        logger.info(f"检测到运行环境: {self.environment}")
    
    def get_team_stats(self, team_id, team_abbr, season, prefer_source=None):
        """
        获取球队赛季统计数据
        
        Args:
            team_id: 球队ID
            team_abbr: 球队缩写
            season: 赛季，如 '2023-24'
            prefer_source: 首选数据源，可选 'nba_api' 或 'bbref'
            
        Returns:
            球队统计数据
        """
        if prefer_source == 'nba_api' or (prefer_source is None and self.environment == 'local'):
            try:
                logger.info(f"使用NBA API获取 {team_abbr} 的 {season} 赛季数据")
                return self.nba_api_client.get_team_stats(team_id, season)
            except Exception as e:
                logger.warning(f"NBA API获取失败，尝试使用Basketball Reference: {e}")
                return self.bbref_scraper.get_team_stats(team_abbr, season)
        else:
            try:
                logger.info(f"使用Basketball Reference获取 {team_abbr} 的 {season} 赛季数据")
                return self.bbref_scraper.get_team_stats(team_abbr, season)
            except Exception as e:
                logger.warning(f"Basketball Reference获取失败，尝试使用NBA API: {e}")
                return self.nba_api_client.get_team_stats(team_id, season)
    
    def get_player_stats(self, player_id, player_bbref_id, season, prefer_source=None):
        """
        获取球员赛季统计数据
        
        Args:
            player_id: NBA API球员ID
            player_bbref_id: Basketball Reference球员ID
            season: 赛季，如 '2023-24'
            prefer_source: 首选数据源，可选 'nba_api' 或 'bbref'
            
        Returns:
            球员统计数据
        """
        if prefer_source == 'nba_api' or (prefer_source is None and self.environment == 'local'):
            try:
                logger.info(f"使用NBA API获取球员 {player_id} 的 {season} 赛季数据")
                return self.nba_api_client.get_player_stats(player_id, season)
            except Exception as e:
                logger.warning(f"NBA API获取失败，尝试使用Basketball Reference: {e}")
                return self.bbref_scraper.get_player_stats(player_bbref_id, season)
        else:
            try:
                logger.info(f"使用Basketball Reference获取球员 {player_bbref_id} 的 {season} 赛季数据")
                return self.bbref_scraper.get_player_stats(player_bbref_id, season)
            except Exception as e:
                logger.warning(f"Basketball Reference获取失败，尝试使用NBA API: {e}")
                return self.nba_api_client.get_player_stats(player_id, season)
    
    def get_player_gamelog(self, player_id, player_bbref_id, season, prefer_source=None):
        """
        获取球员比赛日志
        
        Args:
            player_id: NBA API球员ID
            player_bbref_id: Basketball Reference球员ID
            season: 赛季，如 '2023-24'
            prefer_source: 首选数据源，可选 'nba_api' 或 'bbref'
            
        Returns:
            球员比赛日志数据
        """
        if prefer_source == 'nba_api' or (prefer_source is None and self.environment == 'local'):
            try:
                logger.info(f"使用NBA API获取球员 {player_id} 的 {season} 赛季比赛日志")
                return self.nba_api_client.get_player_gamelog(player_id, season)
            except Exception as e:
                logger.warning(f"NBA API获取失败，尝试使用Basketball Reference: {e}")
                return self.bbref_scraper.get_player_gamelog(player_bbref_id, season)
        else:
            try:
                logger.info(f"使用Basketball Reference获取球员 {player_bbref_id} 的 {season} 赛季比赛日志")
                return self.bbref_scraper.get_player_gamelog(player_bbref_id, season)
            except Exception as e:
                logger.warning(f"Basketball Reference获取失败，尝试使用NBA API: {e}")
                return self.nba_api_client.get_player_gamelog(player_id, season)
    
    def get_team_schedule(self, team_abbr, season, prefer_source='bbref'):
        """
        获取球队赛季赛程
        
        Args:
            team_abbr: 球队缩写
            season: 赛季，如 '2023-24'
            prefer_source: 首选数据源，默认为 'bbref'
            
        Returns:
            球队赛程数据
        """
        # 赛程数据优先使用Basketball Reference
        try:
            logger.info(f"使用Basketball Reference获取 {team_abbr} 的 {season} 赛季赛程")
            return self.bbref_scraper.get_team_schedule(team_abbr, season)
        except Exception as e:
            logger.warning(f"Basketball Reference获取失败: {e}")
            # 可以在这里添加从其他数据源获取赛程的逻辑
            raise
    
    def get_standings(self, season, prefer_source=None):
        """
        获取赛季排名
        
        Args:
            season: 赛季，如 '2023-24'
            prefer_source: 首选数据源，可选 'nba_api' 或 'bbref'
            
        Returns:
            赛季排名数据
        """
        if prefer_source == 'nba_api' or (prefer_source is None and self.environment == 'local'):
            try:
                logger.info(f"使用NBA API获取 {season} 赛季排名")
                return self.nba_api_client.get_standings(season)
            except Exception as e:
                logger.warning(f"NBA API获取失败，尝试使用Basketball Reference: {e}")
                return self.bbref_scraper.get_standings(season)
        else:
            try:
                logger.info(f"使用Basketball Reference获取 {season} 赛季排名")
                return self.bbref_scraper.get_standings(season)
            except Exception as e:
                logger.warning(f"Basketball Reference获取失败，尝试使用NBA API: {e}")
                return self.nba_api_client.get_standings(season)

if __name__ == "__main__":
    # 测试数据源选择器
    selector = DataSourceSelector()
    
    # 测试获取湖人(LAL)的2023-24赛季数据
    try:
        team_stats = selector.get_team_stats('1610612747', 'LAL', '2023-24')
        print("球队统计数据获取成功:")
        print(team_stats.head())
    except Exception as e:
        print(f"测试失败: {e}")