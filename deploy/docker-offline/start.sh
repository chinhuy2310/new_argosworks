#!/bin/bash
set -e
echo "========================================================"
echo "  ARGOS WORKS - Khởi động gói đóng gói Offline"
echo "========================================================"
echo ""

if ! docker image inspect argos-works:latest > /dev/null 2>&1; then
    if [ -f "argos-works-image.tar.gz" ]; then
        echo "[1/2] Đang nạp Docker image từ argos-works-image.tar.gz..."
        docker load -i argos-works-image.tar.gz
    elif [ -f "argos-works-image.tar" ]; then
        echo "[1/2] Đang nạp Docker image từ argos-works-image.tar..."
        docker load -i argos-works-image.tar
    fi
fi

echo "[2/2] Khởi động hệ thống qua Docker Compose..."
docker compose up -d
echo "Hệ thống đang chạy tại: https://localhost/ (hoặc http://localhost:8080)"
