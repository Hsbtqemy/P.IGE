@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

REM 1) Choisir Python (py est le plus fiable sur Windows)
where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py -3
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set PY=python
  ) else (
    echo.
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    echo Then re-run this installer.
    echo.
    pause
    exit /b 1
  )
)

REM 2) Créer le venv
if not exist ".venv" (
  %PY% -m venv .venv
  if %errorlevel% neq 0 (
    echo ERROR: failed to create venv
    pause
    exit /b 1
  )
)

REM 3) Installer PIGE (editable)
call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
call ".venv\Scripts\python.exe" -m pip install -e . 
if %errorlevel% neq 0 (
  echo ERROR: pip install failed
  pause
  exit /b 1
)

REM 4) Créer le launcher .vbs (lance sans console)
(
  echo Set WshShell = CreateObject("WScript.Shell")
  echo base = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
  echo cmd = Chr(34) ^& base ^& "\run_gui.bat" ^& Chr(34)
  echo WshShell.Run cmd, 0
) > "PIGE_GUI.vbs"

REM 5) Créer run_gui.bat (exécuté par le vbs)
(
  echo @echo off
  echo cd /d "%%~dp0"
  echo set "PIGE_DATA_DIR=%%USERPROFILE%%\Documents\PIGE\data"
  echo if not exist "%%PIGE_DATA_DIR%%" mkdir "%%PIGE_DATA_DIR%%"
  echo call ".venv\Scripts\python.exe" -m pige gui
) > "run_gui.bat"

REM 6) (Optionnel) Créer un raccourci sur le Desktop
REM Vous pouvez commenter ce bloc si vous ne voulez pas de shortcut automatique.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\PIGE.lnk'); " ^
  "$lnk.TargetPath = (Resolve-Path '%~dp0PIGE_GUI.vbs'); " ^
  "$lnk.WorkingDirectory = (Resolve-Path '%~dp0'); " ^
  "$lnk.Save()" >nul 2>nul

echo.
echo OK: PIGE installed.
echo Use PIGE_GUI.vbs (or Desktop shortcut 'PIGE') to launch the app without console.
echo Data directory: %USERPROFILE%\Documents\PIGE\data
echo.
pause
endlocal
