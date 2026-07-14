#!/usr/bin/env bash
# NBACore Studio v8 — macOS 一键启动 (start.bat 的 Mac 等价物)
# 用法:  chmod +x start_mac.sh && ./start_mac.sh
set -e

# 强制 UTF-8，避免中文 GBK 解码问题
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
# 清掉公司代理，避免爬虫子进程继承后连 127.0.0.1 报 ECONNREFUSED
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "============================================"
echo "  NBACore Studio v8 - macOS"
echo "============================================"

if ! command -v python3 &> /dev/null; then
  echo "[ERROR] 未检测到 python3，请先安装 Python 3.10+ (brew install python@3.10)"
  exit 1
fi
echo "[1/5] python3: $(python3 --version 2>&1)"

VENV_DIR="$DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "[2/5] 虚拟环境不存在，正在创建..."
  python3 -m venv "$VENV_DIR"
else
  echo "[2/5] 虚拟环境已存在"
fi

echo "[3/5] 安装/校验依赖..."
"$VENV_PIP" install -r requirements.txt || {
  echo "[WARN] 默认源安装失败, 自动切换到 pypi.org 源重试..."
  "$VENV_PIP" install -r requirements.txt -i https://pypi.org/simple
}

if [ -f "$DIR/.env" ]; then
  echo "[4/5] 已加载 .env"
else
  echo "[4/5] 警告: 未找到 .env，复制 .env.example 为 .env 并填好路径"
fi

echo "[5/5] 启动服务..."
echo "  服务地址: http://127.0.0.1:5577"
echo "  前端页面: http://127.0.0.1:5577/app/"
echo "  API 文档: http://127.0.0.1:5577/docs"
echo "  Ctrl+C 停止"
sleep 2
open "http://127.0.0.1:5577/app/" 2>/dev/null || true
exec "$VENV_PYTHON" -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 5577 --log-level info
