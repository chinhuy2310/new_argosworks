@echo off
chcp 65001 > nul
echo Đang tắt hệ thống ARGOS WORKS...
docker compose down
echo.
echo Hệ thống đã được tắt an toàn.
pause
