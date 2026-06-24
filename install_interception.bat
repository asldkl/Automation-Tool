@echo off
chcp 65001 >nul 2>&1
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
sc query interception >nul 2>&1
if %errorlevel% equ 0 (
    echo [信息] 驱动服务已存在。
    sc query interception | findstr "STATE"
    pause
    exit /b 0
)
echo [1/3] 复制驱动文件到系统目录...
copy /Y "%~dp0interception.sys" "C:\Windows\System32\drivers\interception.sys" >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 复制失败！请确认以管理员身份运行。
    pause
    exit /b 1
)
echo       成功。
echo [2/3] 创建驱动服务...
sc create interception type= kernel binPath= "C:\Windows\System32\drivers\interception.sys" >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 创建服务失败！
    pause
    exit /b 1
)
echo       成功。
echo [3/3] 安装完成！
echo.
echo ============================================
echo   请重启电脑使驱动生效！
echo ============================================
echo.
pause
