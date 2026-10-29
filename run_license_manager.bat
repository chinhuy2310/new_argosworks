@echo off
title ARGOS WORKS - Vendor License Manager
cd /d "%~dp0"

echo Dang khoi dong ARGOS WORKS License Manager...
python tools\vendor\license_gui.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [LOI] Khong the khoi chay giao dien License Manager.
    echo Vui long kiem tra Python da duoc cai dat va nam trong bien moi truong PATH.
    pause
)
