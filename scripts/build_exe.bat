@echo off
REM Build the ARGOS WORKS Windows executable package with Nuitka.
REM Prerequisites (once):  pip install -r requirements.txt  &&  pip install nuitka ordered-set zstandard
chcp 65001 > nul
cd /d "%~dp0.."
python scripts\build_exe.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See messages above.
    pause
    exit /b 1
)
echo.
echo Build finished. The package is in the "dist" folder.
pause
