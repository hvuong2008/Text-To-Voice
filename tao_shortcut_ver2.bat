@echo off
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\Lanh Gay Audio TTS ver2.lnk'); $s.TargetPath='%~dp0chay_app_ver2.bat'; $s.WorkingDirectory='%~dp0'; $s.Description='Mo ung dung giong noi ver2'; if (Test-Path '%~dp0icon_ver2.ico') { $s.IconLocation='%~dp0icon_ver2.ico' }; $s.Save()"

if errorlevel 1 (
  echo.
  echo LOI: Khong tao duoc shortcut. Ban van co the mo app bang file chay_app_ver2.bat.
) else (
  echo.
  echo Da tao shortcut "Lanh Gay Audio TTS ver2" ngoai Desktop.
)

if /i not "%~1"=="auto" pause
