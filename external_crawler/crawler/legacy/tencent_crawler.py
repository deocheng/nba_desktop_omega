import json
import os
import requests
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TencentCrawler:
    def __init__(self, data_dir=None):
        """
        初始化腾讯体育爬虫
        :param data_dir: 数据存储目录
        """
        self.data_dir = data_dir or os.path.join(os.path.dirname(__file__), '..')
        
        # 确保数据目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 腾讯体育API基础URL
        self.base_url = "https://sportsdata.tencent.com"
    
    def fetch_todays_games(self, date=None):
        """
        获取今天的比赛数据
        :param date: 日期（格式：YYYY-MM-DD），默认今天
        :return: 比赛数据列表
        """
        if date is None:
            from datetime import date as dt_date
            date = dt_date.today().strftime("%Y-%m-%d")
        
        logger.info(f"获取 {date} 的比赛数据")
        
        # 尝试从本地文件读取（模拟获取数据）
        file_path = os.path.join(self.data_dir, f'tencent_games_{date}.json')
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"成功从本地文件读取 {len(data)} 场比赛数据")
                return data
            except Exception as e:
                logger.error(f"读取本地比赛数据文件失败: {e}")
                return []
        
        # 如果本地文件不存在，返回空列表
        logger.warning(f"未找到 {date} 的比赛数据文件")
        return []
    
    def fetch_players_data(self):
        """
        获取球员详细数据
        :return: 球员数据列表
        """
        logger.info("获取球员详细数据")
        
        # 尝试从本地文件读取（模拟获取数据）
        file_path = os.path.join(self.data_dir, 'tencent_players_detailed.json')
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"成功从本地文件读取 {len(data)} 名球员数据")
                return data
            except Exception as e:
                logger.error(f"读取本地球员数据文件失败: {e}")
                return []
        
        # 如果本地文件不存在，返回空列表
        logger.warning("未找到球员数据文件")
        return []
    
    def fetch_teams_data(self):
        """
        获取球队数据
        :return: 球队数据列表
        """
        logger.info("获取球队数据")
        
        # 尝试从本地文件读取（模拟获取数据）
        file_path = os.path.join(self.data_dir, 'tencent_teams.json')
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"成功从本地文件读取 {len(data)} 支球队数据")
                return data
            except Exception as e:
                logger.error(f"读取本地球队数据文件失败: {e}")
                return []
        
        # 如果本地文件不存在，从球员数据中提取球队信息
        players_data = self.fetch_players_data()
        if players_data:
            teams = {}
            for player in players_data:
                team_id = player.get('team_id')
                if team_id and team_id not in teams:
                    teams[team_id] = {
                        'team_id': team_id,
                        'name': self._get_team_name_by_id(team_id),
                        'abbreviation': team_id[:3] if team_id else None,
                        'conference': self._get_conference(team_id),
                        'division': self._get_division(team_id)
                    }
            teams_list = list(teams.values())
            logger.info(f"从球员数据中提取了 {len(teams_list)} 支球队")
            return teams_list
        
        return []
    
    def _get_team_name_by_id(self, team_id):
        """
        根据球队ID获取球队名称
        """
        team_name_map = {
            '1001': '波士顿凯尔特人',
            '1008': '底特律活塞',
            '2003': '俄克拉荷马城雷霆',
            '2015': '圣安东尼奥马刺',
            '2008': '洛杉矶湖人',
            '2001': '丹佛掘金'
        }
        return team_name_map.get(team_id, '未知球队')
    
    def _get_conference(self, team_id):
        """
        根据球队ID获取联盟
        """
        eastern_teams = ['1001', '1008']  # 凯尔特人、活塞在东部
        western_teams = ['2003', '2015', '2008', '2001']  # 雷霆、马刺、湖人、掘金在西部
        
        if team_id in eastern_teams:
            return '东部'
        elif team_id in western_teams:
            return '西部'
        return None
    
    def _get_division(self, team_id):
        """
        根据球队ID获取分区
        """
        division_map = {
            '1001': '大西洋赛区',
            '1008': '中部赛区',
            '2003': '西北赛区',
            '2015': '西南赛区',
            '2008': '太平洋赛区',
            '2001': '西北赛区'
        }
        return division_map.get(team_id, None)
    
    def fetch_and_save_todays_games(self, date=None):
        """
        获取并保存今天的比赛数据
        :param date: 日期
        :return: 比赛数据列表
        """
        games = self.fetch_todays_games(date)
        if games:
            if date is None:
                from datetime import date as dt_date
                date = dt_date.today().strftime("%Y-%m-%d")
            file_path = os.path.join(self.data_dir, f'tencent_games_{date}.json')
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(games, f, ensure_ascii=False, indent=2)
            logger.info(f"成功保存比赛数据到 {file_path}")
        return games