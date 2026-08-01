#!/bin/bash
# NBA 爬虫控制台启动脚本
cd "$(dirname "$0")/.."
exec .venv/bin/python -m uvicorn crawler_console.app:app --host 127.0.0.1 --port 5599 "$@"
