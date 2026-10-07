@echo off
cd /d "%~dp0"
echo Installing what Tally needs (one time only)...
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo The install did not finish. The Counting can still run using Microsoft Edge, so you can try opening "The Counting.pyw" anyway.
)
echo.
echo Done. Double-click "The Counting.pyw" to start The Counting.
pause
