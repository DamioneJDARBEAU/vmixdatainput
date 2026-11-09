@echo off
rem Record draws that are moved to another time slot or cancelled today,
rem e.g. "Morning draw is being held in the Afternoon slot".
rem The running feeder (run_loop.bat) picks the change up within seconds.
title Fix today's draws
cd /d "%~dp0"
call :findpython || goto :eof
%PY% vmix_lotto_data.py --fix-today
pause
goto :eof

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
