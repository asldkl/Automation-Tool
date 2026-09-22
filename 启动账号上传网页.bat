@echo off
cd /d "%~dp0"
title 账号上传网页
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] 没找到 Python，请先安装 Python 3.8+ 后重试。
  echo.
  pause
  exit /b 1
)
echo 正在启动账号上传网页（关闭本窗口即停止服务）...
echo.
%PY% "账号上传网页.py" %*
echo.
echo 服务已退出。
pause
