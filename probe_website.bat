@echo off
rem Shows every draw number the script can see on the results website,
rem so the matching rules in config.json can be checked or adjusted.
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python was not found. Install Python 3 from https://www.python.org
  pause
  exit /b 1
)
%PY% vmix_lotto_data.py --probe > probe_result.txt 2>&1
type probe_result.txt
echo.
echo The same output was saved to probe_result.txt
pause
