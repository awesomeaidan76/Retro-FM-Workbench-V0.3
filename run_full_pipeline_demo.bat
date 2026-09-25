@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: run_full_pipeline_demo.bat ^<legacy-db-folder^>
  exit /b 2
)
python retro_fm_extractor.py "%~1" -o "%~dp0demo_extract" --parser "%~dp0samples\legacy_parser_demo.py"
