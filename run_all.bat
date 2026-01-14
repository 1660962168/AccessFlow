@echo off
:: =======================================================
::  AccessFlow Launcher (Safe Mode)
:: =======================================================

:: 设置 Anaconda 路径
set ACTIVATE_PATH=D:\anaconda3\Scripts\activate.bat

echo [INFO] Step 1: Checking for MediaMTX...
if exist "mediamtx.exe" (
    echo [OK] Found mediamtx.exe, starting...
    start "0. MediaMTX Service" /min mediamtx.exe
    timeout /t 2 /nobreak >nul
) else (
    echo [WARNING] 'mediamtx.exe' NOT FOUND in this folder!
    echo.
    echo Please make sure you have downloaded MediaMTX and placed
    echo 'mediamtx.exe' inside: %CD%
    echo.
    echo I will try to continue launching Python scripts anyway...
    echo Press any key to continue (or close this window to stop).
    pause
)

echo.
echo [INFO] Step 2: Launching RTSP Streamer...
start "1. RTSP Stream" cmd /k "call %ACTIVATE_PATH% Accessflow && python rtsp.py"

timeout /t 2 /nobreak >nul

echo [INFO] Step 3: Launching OCR Server...
start "2. OCR Server" cmd /k "call %ACTIVATE_PATH% paddle_env && python ocr_server.py"

timeout /t 2 /nobreak >nul

echo [INFO] Step 4: Launching Flask App...
start "3. AccessFlow Web" cmd /k "call %ACTIVATE_PATH% Accessflow && python app.py"

echo.
echo [DONE] Startup sequence finished.
echo This window will close in 5 seconds...
timeout /t 5 >nul
exit