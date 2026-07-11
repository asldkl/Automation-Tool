@echo off
chcp 65001 >nul 2>&1
title Interception 驱动安装
echo ============================================
echo   Interception 驱动一键安装
echo ============================================
echo.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本！
    echo 右键点击此文件 → 以管理员身份运行
    pause
    exit /b 1
)

set SRC=%~dp0interception.sys
set DRV_DIR=C:\Windows\System32\drivers
set DRV_FILE=keyboard.sys
set DRV_PATH=%DRV_DIR%\%DRV_FILE%
set SVC_NAME=keyboard

if not exist "%SRC%" (
    echo [错误] 未找到 %SRC%
    pause
    exit /b 1
)

echo [1/4] 停止并移除旧服务...
sc stop %SVC_NAME% >nul 2>&1
sc delete %SVC_NAME% >nul 2>&1
sc stop interception >nul 2>&1
sc delete interception >nul 2>&1
echo       完成

echo [2/4] 复制驱动到系统目录...
copy /Y "%SRC%" "%DRV_PATH%" >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 复制失败！请确认以管理员身份运行。
    pause
    exit /b 1
)
echo       已复制到 %DRV_PATH%

echo [3/4] 注册驱动服务...
sc create %SVC_NAME% type= kernel binPath= "%DRV_PATH%" >nul 2>&1
if %errorlevel% equ 0 (
    echo       服务创建成功
) else (
    echo       服务已存在，跳过
)

echo [4/4] 启动驱动...
sc start %SVC_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo       驱动已成功启动！✅
) else (
    echo [警告] 驱动启动失败（错误码: %errorlevel%）
    echo.
    echo 原因: Windows 驱动签名强制 (DSE)
    echo 解决方法: 以管理员身份运行:
    echo   bcdedit /set testsigning on
    echo 然后重启电脑
)

echo.
echo ============================================
sc query %SVC_NAME% | findstr "STATE"
echo ============================================
pause
