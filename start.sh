#!/usr/bin/env bash
# start.sh — Production entrypoint for First Reply Tajweed.
# Usage: ./start.sh  (or used as Docker CMD)

set -euo pipefail

echo "══════════════════════════════════════════════"
echo "  First Reply Tajweed — Starting…"
echo "══════════════════════════════════════════════"

# Ensure sessions directory exists
mkdir -p /app/sessions

# Validate required environment variables
REQUIRED_VARS="API_ID API_HASH PHONE BOT_TOKEN OWNER_ID TARGET_CHAT"
MISSING=""
for var in $REQUIRED_VARS; do
    if [ -z "${!var:-}" ]; then
        MISSING="$MISSING $var"
    fi
done

if [ -n "$MISSING" ]; then
    echo "FATAL: Missing required environment variables:$MISSING"
    echo "Set them in .env or EasyPanel environment settings."
    exit 1
fi

echo "✅ All required environment variables present"
echo "Starting Python application…"

exec python main.py
