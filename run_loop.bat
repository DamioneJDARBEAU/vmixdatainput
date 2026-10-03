@echo off
rem Keeps the vMix title data fresh: updates every 5 minutes (300 seconds).
rem Leave this window open (it can be minimised). Close it to stop.
title vMix Lotto Data Feeder
cd /d "%~dp0"
call :findpython || goto :eof

:again
%PY% vmix_lotto_data.py --loop 300
echo.
echo The feeder stopped unexpectedly. Restarting in 30 seconds...
timeout /t 30 /nobreak >nul
goto again

:findpython
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python was not found. Install Python 3 from https://www.python.org
  echo and tick "Add python.exe to PATH" during install.
  pause
  exit /b 1
)
exit /b 0
