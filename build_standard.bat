@echo off
REM ==============================================================================
REM ARGOS WORKS - Build Standard Edition (Lightweight / Cloud-Ready)
REM Không kèm Ollama & Model (Dung lượng siêu nhẹ ~150MB)
REM ==============================================================================
chcp 65001 > nul
cd /d "%~dp0"

echo [1/2] Đang biên dịch mã nguồn và đóng gói bản Standard...
python scripts\build_exe.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Biên dịch thất bại. Vui lòng kiểm tra thông báo lỗi ở trên.
    pause
    exit /b 1
)

echo.
echo [2/2] Kiểm tra trình tạo bộ cài đặt Inno Setup (Setup.exe)...
set ISCC_PATH=
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\iscc.exe" set "ISCC_PATH=%LOCALAPPDATA%\Programs\Inno Setup 6\iscc.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\iscc.exe" set "ISCC_PATH=%ProgramFiles(x86)%\Inno Setup 6\iscc.exe"
if exist "%ProgramFiles%\Inno Setup 6\iscc.exe" set "ISCC_PATH=%ProgramFiles%\Inno Setup 6\iscc.exe"
if not defined ISCC_PATH (
    where iscc >nul 2>&1
    if not errorlevel 1 set "ISCC_PATH=iscc"
)

if defined ISCC_PATH (
    echo Đang tạo file cài đặt Windows Setup.exe qua Inno Setup...
    "%ISCC_PATH%" /DBuildType=standard installer\argosworks_setup.iss
    if not errorlevel 1 (
        echo.
        echo [THÀNH CÔNG] File cài đặt Setup đã được tạo trong thư mục dist\
    )
) else (
    echo [INFO] Chưa tìm thấy Inno Setup 6. Gói ứng dụng chuẩn (.zip và thư mục) đã có sẵn trong dist\
    echo (Nếu muốn tạo file Setup.exe nguyên khối, bạn có thể cài: winget install JRSoftware.InnoSetup)
)

echo.
echo ==============================================================================
echo ĐÃ HOÀN TẤT ĐÓNG GÓI BẢN STANDARD
echo ==============================================================================
pause
