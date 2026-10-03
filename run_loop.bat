@echo off
rem Keeps the vMix title data fresh: updates every 5 minutes.
cd /d "%~dp0"
python vmix_lotto_data.py --loop 300
