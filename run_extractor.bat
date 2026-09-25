@echo off
cd /d "%~dp0"
python retro_fm_extractor.py %*
if errorlevel 1 pause
