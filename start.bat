@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM Force UTF-8 for Python to avoid GBK decoding errors
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Unset proxy so the crawler subprocess (spawned via subprocess) does not
REM inherit http_proxy/https_proxy and fail with ECONNREFUSED to 127.0.0.1:xxxx
set http_proxy=
set https_proxy=
set HTTP_PROXY=
set HTTPS_PROXY=
set all_proxy=
set ALL_PROXY=

title NBACore Studio v8 - 一键启动

echo ============================================================
echo   NBA Core Studio v8 - 球员数据分析平台
echo ============================================================
echo.

REM 获取脚本所在目录
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 或更高版本
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%a in ('python --version 2^>^&1') do set PYTHON_VERSION=%%a
echo [1/5] Python 已安装: %PYTHON_VERSION%

REM 检查虚拟环境
set "VENV_DIR=%PROJECT_DIR%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [2/5] 虚拟环境不存在，正在创建...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [2/5] 虚拟环境创建完成
) else (
    echo [2/5] 虚拟环境已存在
)

REM 升级 pip 避免编码问题
echo [3/5] 升级 pip...
"%VENV_PYTHON%" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1

REM 检查并安装依赖
echo [3/5] 检查依赖...
"%VENV_PYTHON%" -c "import fastapi, uvicorn, psycopg2, pandas, numpy, pydantic, diskcache" >nul 2>&1
if errorlevel 1 (
    echo [3/5] 安装依赖中，请稍候...
    "%VENV_PIP%" install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
    echo [3/5] 依赖安装完成
) else (
    echo [3/5] 依赖已满足
)

REM 读取环境变量
if exist "%PROJECT_DIR%.env" (
    echo [4/5] 已加载 .env 配置文件
) else (
    echo [4/5] 警告: 未找到 .env 文件，将使用默认配置
    echo        如需配置数据库连接，请复制 .env.example 为 .env
)

REM 启动服务器
echo [5/5] 启动服务器...
echo.
echo ============================================================
echo   服务地址: http://127.0.0.1:5577
echo   前端页面: http://127.0.0.1:5577/app/
echo   API 文档: http://127.0.0.1:5577/docs
echo ============================================================
echo   按 Ctrl+C 停止服务
echo ============================================================
echo.

REM 延迟 2 秒后打开浏览器
ping -n 3 127.0.0.1 >nul
start "" "http://127.0.0.1:5577/app/"

REM 启动 uvicorn
"%VENV_PYTHON%" -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 5577 --log-level info

echo.
echo 服务已停止
timeout /t 2 /nobreak >nul
endlocal
