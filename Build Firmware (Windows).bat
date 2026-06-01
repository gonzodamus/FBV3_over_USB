@echo off
REM Double-click this file to build the patched FBV3 firmware on Windows.
REM It turns your own copy of the stock Line 6 firmware into the patched version
REM that adds USB LED control. Nothing is sent anywhere; it all happens on your PC.

REM Work from the folder this script lives in (so double-clicking "just works").
cd /d "%~dp0"

echo.
echo FBV3 over USB: firmware builder
echo ===================================
echo.

set "STOCK=firmware\Fbv3_v1_02_00.hxf"

REM 1. Make sure the stock firmware is present.
if not exist "%STOCK%" (
  echo I need the original Line 6 firmware first.
  echo.
  echo   1. Download the FBV3 firmware update from Line 6 ^(file name like
  echo      'Fbv3_v1_02_00.hxf'^). If you've ever run the Line 6 FBV3 Updater,
  echo      it's already on your computer.
  echo   2. Put that file into this folder:
  echo.
  echo        %CD%\firmware\
  echo.
  echo      and make sure it's named exactly:  Fbv3_v1_02_00.hxf
  echo   3. Then double-click this script again.
  echo.
  pause
  exit /b 1
)

REM 2. Find Python 3 (the "py" launcher or python on PATH).
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python 3 isn't installed.
  echo.
  echo Install it from https://www.python.org/downloads/ ^(check "Add Python to
  echo PATH" during setup^), then double-click this script again.
  echo.
  pause
  exit /b 1
)

REM 3. Build.
echo Building the patched firmware...
echo.
%PY% build\build_firmware.py
if errorlevel 1 (
  echo.
  echo Something went wrong. Please copy the messages above and open an
  echo issue on the project's GitHub page so we can help.
  echo.
  pause
  exit /b 1
)

echo.
echo Success!
echo.
echo Your patched firmware is here:
echo   %CD%\firmware\Fbv3_Chroma_1.1.hxf
echo.
echo Next: flash it with the Line 6 FBV3 Updater (see the README's
echo "Flash the firmware" steps).
echo.
pause
