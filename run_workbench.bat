@echo off
cd /d "%~dp0"
python retro_fm_workbench.py
if errorlevel 1 pause
