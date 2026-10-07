@echo off
cd /d "%~dp0"
echo Building The Counting. This takes a few minutes the first time.
py -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail
py -m PyInstaller --noconfirm --clean --windowed --name "The Counting" --add-data "tally_app\web;tally_app\web" --collect-submodules webview --collect-data certifi run_thecounting.py
if errorlevel 1 goto :fail
echo.
echo Done. Your app is in dist\The Counting\The Counting.exe
echo Tip: right-click The Counting.exe, choose Show more options, then Send to, then Desktop (create shortcut).
explorer "dist\The Counting"
pause
exit /b 0
:fail
echo.
echo The build did not finish. Scroll up to see the message, or see README.md.
pause
exit /b 1
