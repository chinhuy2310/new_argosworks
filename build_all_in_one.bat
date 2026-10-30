@echo off
REM ==============================================================================
REM ARGOS WORKS - Build All-In-One Edition (Offline / Air-Gapped Local AI)
REM Kèm sẵn Ollama + Model bge-m3 (Dung lượng ~1.3GB)
REM ==============================================================================
chcp 65001 > nul
cd /d "%~dp0"

echo ==============================================================================
echo [BƯỚC 1/3] Chuẩn bị tệp chạy Ollama và Model bge-m3 vào vendor\ollama...
echo ==============================================================================

if not exist "vendor\ollama" mkdir "vendor\ollama"
if not exist "vendor\ollama\models" mkdir "vendor\ollama\models"

REM Copy ollama.exe từ cài đặt hệ thống nếu chưa có trong vendor
if not exist "vendor\ollama\ollama.exe" (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        echo Đang sao chép ollama.exe từ %LOCALAPPDATA%\Programs\Ollama...
        copy /y "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" "vendor\ollama\ollama.exe" >nul
    ) else (
        echo [CẢNH BÁO] Không tìm thấy ollama.exe trên máy. Vui lòng cài Ollama trước.
    )
)

REM Đồng bộ model bge-m3 từ .ollama sang vendor\ollama\models
if exist "%USERPROFILE%\.ollama\models" (
    echo Đang đồng bộ model bge-m3 vào vendor\ollama\models...
    xcopy "%USERPROFILE%\.ollama\models" "vendor\ollama\models" /E /I /Y /Q >nul
) else (
    echo [CẢNH BÁO] Chưa tìm thấy model bge-m3 trong %USERPROFILE%\.ollama\models.
    echo Vui lòng chạy lệnh 'ollama pull bge-m3' trước khi đóng gói bản All-In-One.
)

echo.
echo ==============================================================================
echo [BƯỚC 2/3] Biên dịch mã nguồn và đóng gói All-In-One (--embed-ai)...
echo ==============================================================================
python scripts\build_exe.py --embed-ai %*
if errorlevel 1 (
    echo.
    echo [ERROR] Biên dịch thất bại. Vui lòng kiểm tra thông báo lỗi ở trên.
    pause
    exit /b 1
)

echo.
echo ==============================================================================
echo [BƯỚC 3/3] Kiểm tra trình tạo bộ cài đặt Inno Setup (Setup.exe)...
echo ==============================================================================
set ISCC_PATH=
if exist "%ProgramFiles(x86)%\Inno Setup 6\iscc.exe" set "ISCC_PATH=%ProgramFiles(x86)%\Inno Setup 6\iscc.exe"
if exist "%ProgramFiles%\Inno Setup 6\iscc.exe" set "ISCC_PATH=%ProgramFiles%\Inno Setup 6\iscc.exe"
if not defined ISCC_PATH (
    where iscc >nul 2>&1
    if not errorlevel 1 set "ISCC_PATH=iscc"
)

if defined ISCC_PATH (
    echo Đang tạo file cài đặt Windows Setup.exe (All-In-One) qua Inno Setup...
    "%ISCC_PATH%" /DBuildType=ai installer\argosworks_setup.iss
    if not errorlevel 1 (
        echo.
        echo [THÀNH CÔNG] File cài đặt Setup All-In-One đã được tạo trong thư mục dist\
    )
) else (
    echo [INFO] Chưa tìm thấy Inno Setup 6. Gói All-In-One (.zip và thư mục) đã có sẵn trong dist\
    echo (Nếu muốn tạo file Setup.exe nguyên khối, bạn có thể cài: winget install JRSoftware.InnoSetup)
)

echo.
echo ==============================================================================
echo ĐÃ HOÀN TẤT ĐÓNG GÓI BẢN ALL-IN-ONE (EMBEDDED LOCAL AI)
echo ==============================================================================
pause
