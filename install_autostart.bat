@echo off
rem Makes the feeder start automatically when this Windows user logs on.
rem Right-click this file and choose "Run as administrator".
cd /d "%~dp0"
schtasks /Create /TN "vMix Lotto Data Feeder" /TR "\"%~dp0run_loop.bat\"" /SC ONLOGON /RL HIGHEST /F
if errorlevel 1 (
  echo.
  echo Could not create the task. Make sure you used "Run as administrator".
) else (
  echo.
  echo Done. The feeder will start each time you log on.
  echo To start it now, double-click run_loop.bat.
)
pause
