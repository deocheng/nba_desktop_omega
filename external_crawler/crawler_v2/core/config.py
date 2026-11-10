#!/usr/bin/env python3
"""
core/config.py — v2 统一配置（stdlib 优先，零 python-dotenv 强制依赖）。

与旧版约定保持一致：
  - DB 凭据从环境变量取，缺省 localhost:5433 / nba / postgres（与 br_fill_pbp.py 同）。
  - 可选从项目 .env 读取（若已装 dotenv 则自动加载，没装也不报错，沿用旧行为）。
  - 出站前需 unset http_proxy/https_proxy（旧 recrawl 脚本的纪律，这里集中管理）。
"""
import os

# 可选 dotenv：装了就加载，没装静默跳过（不强行引入依赖，遵守栈纪律）
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


def get_db_config() -> dict:
    """返回 psycopg2.connect 用的 dict。key 名沿用旧版 (database)。"""
    return dict(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5433)),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("PGPASSWORD", ""),
        dbname=os.environ.get("DB_NAME", "nba"),
    )


def get_cdp_url() -> str:
    return os.environ.get("CHROME_CDP_URL", "http://127.0.0.1:9223")


def clear_outbound_proxy():
    """出站前清代理（BR 直连，不走系统代理）。"""
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


# BR 硬限速（旧 br_fill_pbp.RateLimiter 的常量，集中到配置）
BR_RATE_PER_MINUTE = int(os.environ.get("BR_RATE_PER_MINUTE", 15))
BR_MIN_INTERVAL = float(os.environ.get("BR_MIN_INTERVAL", 4.5))

# cf_clearance 绑定 IP 的近似寿命（分钟）。旧 cf_breaker: 约 30-60min 过期。
CF_CLEARANCE_TTL_MIN = int(os.environ.get("CF_CLEARANCE_TTL_MIN", 45))
