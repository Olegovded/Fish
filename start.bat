@echo off
rem Запуск бота на Windows двойным кликом.
rem При первом запуске создаёт окружение и ставит зависимости, дальше просто запускает.
cd /d "%~dp0"

if not exist .env (
    echo.
    echo [!] File .env not found. Create it next to start.bat with two lines:
    echo     BOT_TOKEN=your_token_from_botfather
    echo     BOT_USERNAME=Ribakru_bot
    echo.
    pause
    exit /b 1
)

if not exist .venv\Scripts\python.exe (
    echo First run: creating environment and installing packages, please wait...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo [!] Python not found. Install it from https://www.python.org/downloads/
        echo     During install TICK the box "Add python.exe to PATH", then retry.
        echo.
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo.
echo Bot is starting. Open @Ribakru_bot in Telegram and press /start.
echo To stop: close this window or press Ctrl+C.
echo.
.venv\Scripts\python.exe -m bot.main
pause
