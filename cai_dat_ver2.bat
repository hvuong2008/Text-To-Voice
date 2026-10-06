@echo off
cd /d "%~dp0"
echo ==================================================
echo   CAI DAT UNG DUNG DOC VAN BAN - BAN VER2
echo   (chi can lam 1 lan, dung chung moi truong venv
echo    voi ban cu neu da co)
echo ==================================================
echo.

if exist venv\Scripts\python.exe goto install

echo [1/4] Dang tao moi truong rieng bang Python 3.12...
py -3.12 -m venv venv
if not errorlevel 1 goto install

echo.
echo Khong tim thay Python 3.12, thu dung Python mac dinh...
echo (Che do "Giong cua toi" co the khong cai duoc, nhung Edge TTS van dung binh thuong)
python -m venv venv
if errorlevel 1 (
  echo.
  echo LOI: Khong tim thay Python tren may.
  echo Hay cai Python 3.12 tu https://www.python.org/downloads/
  echo Nho tick vao o "Add python.exe to PATH" khi cai, roi chay lai file nay.
  pause
  exit /b 1
)

:install
echo.
echo [2/4] Dang cai thu vien co ban: gradio, edge-tts, imageio-ffmpeg (mat vai phut)...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install --upgrade gradio edge-tts imageio-ffmpeg
if errorlevel 1 (
  echo.
  echo LOI: Cai thu vien co ban that bai. Hay kiem tra ket noi Internet roi chay lai.
  pause
  exit /b 1
)

echo.
echo [3/4] Dang cai thu vien chuyen giong noi thanh van ban: faster-whisper (mat vai phut)...
venv\Scripts\python.exe -m pip install --upgrade faster-whisper
if errorlevel 1 (
  echo.
  echo CANH BAO: Khong cai duoc faster-whisper. Chuc nang "Giong noi sang Van ban" se chua dung duoc.
  echo Cac chuc nang con lai van hoat dong binh thuong.
) else (
  echo.
  echo Da cai xong chuc nang giong noi sang van ban.
)

echo.
echo [4/4] Dang cai thu vien nhan ban giong: vieneu (mat vai phut)...
venv\Scripts\python.exe -m pip install --upgrade vieneu
if errorlevel 1 (
  echo.
  echo CANH BAO: Khong cai duoc vieneu. Che do "Giong cua toi" se chua dung duoc.
  echo Cac giong co san (Edge TTS) van hoat dong binh thuong.
) else (
  echo.
  echo Da cai xong ca che do nhan ban giong.
)

echo.
echo Dang tao shortcut ngoai Desktop...
call tao_shortcut_ver2.bat auto

echo.
echo ==================================================
echo   XONG! Tu gio chi can bam vao shortcut ngoai Desktop
echo   (hoac mo file chay_app_ver2.bat) de dung app.
echo ==================================================
pause
