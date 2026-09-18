@echo off
REM qq-agent-bridge 一键启动（Windows / CMD）
REM   start.bat              首次运行自动建 venv、装依赖、然后启动
REM   start.bat --no-install 跳过依赖安装
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYTHON=python"
if defined PYTHON_BIN set "PYTHON=%PYTHON_BIN%"

set "INSTALL=1"
if "%~1"=="--no-install" set "INSTALL=0"

where %PYTHON% >nul 2>nul
if errorlevel 1 (
  echo 找不到 Python：%PYTHON%（请安装 Python 3.10+ 并勾选 Add to PATH） 1>&2
  exit /b 1
)

if not exist ".venv" (
  echo ==^> 创建虚拟环境 .venv
  %PYTHON% -m venv .venv || exit /b 1
)

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo 虚拟环境不完整，请删除 .venv 后重试 1>&2
  exit /b 1
)

if "%INSTALL%"=="1" (
  echo ==^> 安装依赖（核心 + agno 后端）
  "%VENV_PY%" -m pip install --quiet --upgrade pip
  "%VENV_PY%" -m pip install --quiet -r requirements.txt
  "%VENV_PY%" -m pip install --quiet -r requirements-agno.txt
  if errorlevel 1 echo !! agno 后端安装失败，可先只用 Codex CLI 后端 1>&2
)

if not exist "config.json" (
  copy /y config.example.json config.json >nul
  echo !! 已生成 config.json，请先把 full_access_qq 改成你自己的 QQ 号再启动 1>&2
  echo    编辑器打开：config.json 1>&2
  exit /b 2
)

echo ==^> 启动 qq-agent-bridge（Ctrl-C 退出）
"%VENV_PY%" bridge.py
endlocal
