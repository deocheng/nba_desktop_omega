from data_source_manager import DataSourceManager
import time
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NBACrawler:
    def __init__(self, cache_expiry=86400):
        """
        初始化 NBA 爬虫
        :param cache_expiry: 缓存过期时间（秒）
        """
        self.data_source = DataSourceManager(cache_expiry=cache_expiry)
    
    def crawl_player_career_stats(self, player_id):
        """
        爬取球员职业生涯统计数据
        :param player_id: 球员ID
        :return: 球员职业生涯统计数据
        """
        logger.info(f"爬取球员 {player_id} 的职业生涯统计数据")
        try:
            data = self.data_source.get_player_career_stats(player_id)
            logger.info(f"成功爬取球员 {player_id} 的职业生涯统计数据，共 {len(data)} 条记录")
            return data
        except Exception as e:
            logger.error(f"爬取球员 {player_id} 的职业生涯统计数据失败: {e}")
            return []
    
    def crawl_team_info(self, team_id):
        """
        爬取球队信息
        :param team_id: 球队ID
        :return: 球队信息
        """
        logger.info(f"爬取球队 {team_id} 的信息")
        try:
            data = self.data_source.get_team_info(team_id)
            logger.info(f"成功爬取球队 {team_id} 的信息")
            return data
        except Exception as e:
            logger.error(f"爬取球队 {team_id} 的信息失败: {e}")
            return {}
    
    def crawl_player_info(self, player_id):
        """
        爬取球员信息
        :param player_id: 球员ID
        :return: 球员信息
        """
        logger.info(f"爬取球员 {player_id} 的信息")
        try:
            data = self.data_source.get_player_info(player_id)
            logger.info(f"成功爬取球员 {player_id} 的信息")
            return data
        except Exception as e:
            logger.error(f"爬取球员 {player_id} 的信息失败: {e}")
            return {}
    
    def crawl_team_info_static(self, team_id):
        """
        爬取静态球队信息
        :param team_id: 球队ID
        :return: 球队信息
        """
        logger.info(f"爬取球队 {team_id} 的静态信息")
        try:
            data = self.data_source.get_team_info_static(team_id)
            logger.info(f"成功爬取球队 {team_id} 的静态信息")
            return data
        except Exception as e:
            logger.error(f"爬取球队 {team_id} 的静态信息失败: {e}")
            return {}
    
    def crawl_games(self, team_id, season):
        """
        爬取球队赛季比赛数据
        :param team_id: 球队ID
        :param season: 赛季（格式：YYYY-YY）
        :return: 比赛数据
        """
        logger.info(f"爬取球队 {team_id} 在 {season} 赛季的比赛数据")
        try:
            data = self.data_source.get_games(team_id, season)
            logger.info(f"成功爬取球队 {team_id} 在 {season} 赛季的比赛数据，共 {len(data)} 场比赛")
            return data
        except Exception as e:
            logger.error(f"爬取球队 {team_id} 在 {season} 赛季的比赛数据失败: {e}")
            return []
    
    def crawl_all_players(self):
        """
        爬取所有球员信息
        :return: 所有球员信息
        """
        logger.info("爬取所有球员信息")
        try:
            data = self.data_source.get_all_players()
            logger.info(f"成功爬取所有球员信息，共 {len(data)} 名球员")
            return data
        except Exception as e:
            logger.error(f"爬取所有球员信息失败: {e}")
            return []
    
    def crawl_all_teams(self):
        """
        爬取所有球队信息
        :return: 所有球队信息
        """
        logger.info("爬取所有球队信息")
        try:
            data = self.data_source.get_all_teams()
            logger.info(f"成功爬取所有球队信息，共 {len(data)} 支球队")
            return data
        except Exception as e:
            logger.error(f"爬取所有球队信息失败: {e}")
            return []
    
    def crawl_multiple_players(self, player_ids, delay=1):
        """
        爬取多个球员的信息
        :param player_ids: 球员ID列表
        :param delay: 爬取间隔（秒）
        :return: 球员信息列表
        """
        players_info = []
        for player_id in player_ids:
            info = self.crawl_player_info(player_id)
            if info:
                players_info.append(info)
            time.sleep(delay)  # 避免请求过快
        return players_info
    
    def crawl_multiple_teams(self, team_ids, delay=1):
        """
        爬取多个球队的信息
        :param team_ids: 球队ID列表
        :param delay: 爬取间隔（秒）
        :return: 球队信息列表
        """
        teams_info = []
        for team_id in team_ids:
            info = self.crawl_team_info_static(team_id)
            if info:
                teams_info.append(info)
            time.sleep(delay)  # 避免请求过快
        return teams_info
