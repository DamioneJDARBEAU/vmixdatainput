@echo off
rem Updates the vMix title data (date + next draw IDs) one time.
cd /d "%~dp0"
call :findpython || goto :eof
call :askchanges
%PY% vmix_lotto_data.py
if errorlevel 1 (
  echo.
  echo Something went wrong - read the messages above.
)
pause
goto :eof

:askchanges
rem Before processing: were any draws moved or cancelled today?
echo.
choice /C YN /T 15 /D N /M "Any draw changes today (moved or cancelled draws)? No answer in 15 s = No"
if errorlevel 2 exit /b 0
%PY% vmix_lotto_data.py --fix-today
exit /b 0

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
