@echo off
chcp 65001 > nul
echo ========================================================
echo   ARGOS WORKS - Khởi động gói đóng gói Offline
echo ========================================================
echo.

REM 1. Nạp Docker Image offline nếu chưa có
docker image inspect argos-works:latest > nul 2>&1
if errorlevel 1 (
    if exist "argos-works-image.tar.gz" (
        echo [1/3] Đang nạp Docker image từ argos-works-image.tar.gz...
        docker load -i argos-works-image.tar.gz
    ) else if exist "argos-works-image.tar" (
        echo [1/3] Đang nạp Docker image từ argos-works-image.tar...
        docker load -i argos-works-image.tar
    ) else (
        echo [CẢNH BÁO] Không tìm thấy file image offline, sẽ thử tải online...
    )
) else (
    echo [1/3] Docker image đã có sẵn trên máy.
)

REM 2. Khởi động các container qua docker compose
echo [2/3] Đang khởi động hệ thống (App + PostgreSQL + Caddy HTTPS)...
docker compose up -d

REM 3. Chờ và mở trình duyệt
echo [3/3] Hệ thống đã sẵn sàng! Đang mở trình duyệt...
timeout /t 4 > nul
start https://localhost/
echo.
echo ========================================================
echo   Đang chạy tại: https://localhost/ (hoặc http://localhost:8080)
echo   Để tắt hệ thống, bấm đúp vào file 'stop.bat'.
echo ========================================================
pause
