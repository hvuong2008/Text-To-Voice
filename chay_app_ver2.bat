@echo off
cd /d "%~dp0"
set GRADIO_ANALYTICS_ENABLED=False

if not exist venv\Scripts\python.exe (
  echo Chua cai dat. Hay bam dup vao file cai_dat_ver2.bat truoc.
  pause
  exit /b 1
)

echo Dang khoi dong ung dung (ver2), vui long cho trong giay lat...
echo (Dong cua so den nay de tat ung dung.)
venv\Scripts\python.exe app_ver2.py
pause
