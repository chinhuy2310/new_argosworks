@echo off
chcp 65001 > nul
title ARGOS WORKS Server
echo ========================================================
echo   Starting the ARGOS WORKS backend server...
echo   When [READY] appears, open the URL printed by the banner
echo   (default: https://localhost:8443 or http://127.0.0.1:8080)
echo ========================================================
python server\main.py
pause
