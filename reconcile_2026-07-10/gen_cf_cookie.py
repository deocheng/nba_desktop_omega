"""
gen_cf_cookie.py — 仅用于生成 Cloudflare 绕过 cookie，不抓取数据、不写库。

机制：复用 nba_daily_crawler.BrowserManager。
  启动单会话浏览器 -> 导航到 basketball-reference.com 首页 ->
  过 CF 后 BrowserManager._try_get_real_page 自动调用 _save_cookies() ->
  把 cookie 落盘到 C:\autopick\AutoPick\nba_data\.br_cf_cookies.pkl -> 退出。

用法（在项目 nba_data 根目录执行，禁用代理）：
  cd /c/autopick/AutoPick/nba_data
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    /c/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe \
    nba_desktop/nba_desktop_omega/reconcile_2026-07-10/gen_cf_cookie.py

注意：
  - 若 Cloudflare 弹出 CAPTCHA 人机验证，本脚本（headless）无法通过；
    需在可见浏览器手动点过一次，或改用 nba_daily_crawler.py 的某抓取模式
    （如 `python nba_daily_crawler.py --month-backfill 2025-10`）在首次
    成功抓取 BR 页面时落盘 cookie。
  - cf_clearance 有 TTL（通常数小时~1 天）。生成后尽快跑
    _fetch_br_2026_schedule.py，过期则需重来。
"""
import os
import sys
import logging

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)

HERE = os.path.dirname(os.path.abspath(__file__))
# reconcile_2026-07-10 -> nba_desktop_omega -> nba_desktop -> nba_data（三级上溯）
NBA_DATA = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, NBA_DATA)

from nba_daily_crawler import BrowserManager  # noqa: E402

log = logging.getLogger('gen_cf_cookie')
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')

BM = BrowserManager(log)
BM.start()  # 注入已有 cookie（若有），启动单会话 driver

# 导航到 BR 首页；过 CF 后 BrowserManager 自动 _save_cookies()
page = BM.fetch_page('https://www.basketball-reference.com/', cf_timeout=90)
if page is None:
    log.warning('未能通过 Cloudflare（可能是 CAPTCHA）。'
                '请在可见浏览器手动解决后重试，或改用 crawler 抓取模式。')
else:
    log.info('已获取 BR 页面，cookie 应已落盘。')

BM.quit()

cookie_file = os.path.join(NBA_DATA, '.br_cf_cookies.pkl')
if os.path.exists(cookie_file):
    print('OK: cookie 已生成 ->', cookie_file)
else:
    print('FAIL: cookie 未生成，请检查 Cloudflare 挑战是否通过。')
