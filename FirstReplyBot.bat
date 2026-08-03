@echo off
chcp 65001 >nul 2>&1
title First Reply Tajweed Bot
color 0A

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║                                                      ║
echo  ║   █▀▀ █ █▀█ █▀ ▀█▀   █▀█ █▀▀ █▀█ █   █▄█           ║
echo  ║   █▀  █ █▀▄ ▄█  █    █▀▄ ██▄ █▀▀ █▄▄  █            ║
echo  ║                                                      ║
echo  ║   First Reply Tajweed Bot                             ║
echo  ║   Telegram Auto-Reply System                          ║
echo  ║                                                      ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║                                                      ║
echo  ║   ⚡ Zero-delay reply mode                           ║
echo  ║   🔒 Device spoofing (Galaxy S24 Ultra)              ║
echo  ║   🤖 Control bot: /arm /stop /status                 ║
echo  ║   📡 Persistent service mode                         ║
echo  ║                                                      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  Press Ctrl+C to stop the bot at any time.
echo  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

cd /d "%~dp0"

if not exist ".env" (
    echo  ❌ ERROR: .env file not found!
    echo  Create a .env file with your credentials.
    echo  See .env.example for reference.
    echo.
    pause
    exit /b 1
)

python launcher.py

if %errorlevel% neq 0 (
    echo.
    echo  ❌ Bot exited with an error.
    echo.
    pause
)
