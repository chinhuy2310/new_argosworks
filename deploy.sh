#!/usr/bin/env bash
# ==============================================================================
# ARGOS WORKS - Automated 1-Click Deployment Script
# ==============================================================================
set -e

echo "=========================================================="
echo " ARGOS WORKS - Deployment Script"
echo "=========================================================="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed on this system."
    echo "Please install Docker and Docker Compose before running this script."
    exit 1
fi

# Ensure data directory exists on host
mkdir -p data/backups data/attachments data/templates

# ------------------------------------------------------------------------------
# First-run bootstrap
#   - .env with freshly generated ARGOS_MASTER_KEY / POSTGRES_PASSWORD
#   - server/config.json as a real file (Docker bind-mounts it; if it is missing
#     Docker creates a directory and the app can no longer persist settings)
#   - persistent data directories
# ------------------------------------------------------------------------------
if command -v python3 &> /dev/null; then
    python3 scripts/init_deploy.py
elif command -v python &> /dev/null; then
    python scripts/init_deploy.py
else
    echo "⚠️ Python not found - falling back to shell bootstrap."
    if [ ! -f .env ]; then
        if command -v openssl &> /dev/null; then
            MASTER_KEY=$(openssl rand -hex 32)
            PG_PASSWORD=$(openssl rand -hex 16)
            sed -e "s|^ARGOS_MASTER_KEY=.*|ARGOS_MASTER_KEY=${MASTER_KEY}|" \
                -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PG_PASSWORD}|" \
                -e "s|YOUR_STRONG_PASSWORD_HERE|${PG_PASSWORD}|g" \
                .env.example > .env
            echo "✅ .env created with freshly generated secrets"
        else
            echo "❌ Cannot generate .env secrets: install python3 or openssl, then re-run."
            exit 1
        fi
    fi
    if [ ! -f server/config.json ]; then
        echo "⚠️ Warning: server/config.json not found. Initializing from config.example.json..."
        mkdir -p server
        if [ -f server/config.example.json ]; then
            cp server/config.example.json server/config.json
        else
            echo '{"server":{"host":"0.0.0.0","port":8080}}' > server/config.json
        fi
    fi
fi

echo "🚀 Building and starting ARGOS WORKS container via Docker Compose..."
if docker compose version &> /dev/null; then
    docker compose up -d --build
else
    docker-compose up -d --build
fi

echo ""
echo "=========================================================="
echo " ✅ ARGOS WORKS is successfully deployed with HTTPS!"
echo " 🌐 HTTPS URL: https://${DOMAIN:-localhost} (Port 443 - SSL/TLS Secured)"
echo " 🌐 HTTP  URL: http://${DOMAIN:-localhost}  (Port 80  - Auto redirects to HTTPS)"
echo " To view logs: docker compose logs -f"
echo " To stop     : docker compose down"
echo "=========================================================="
