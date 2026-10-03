@echo off
rem Stops the feeder from starting automatically at log on.
rem Right-click this file and choose "Run as administrator".
schtasks /Delete /TN "vMix Lotto Data Feeder" /F
pause
