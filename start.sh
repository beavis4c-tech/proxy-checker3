#!/usr/bin/env bash
set -e

echo "============================================"
echo " Cloud Proxy Checker — Render Startup"
echo "============================================"

# Move into the correct directory
cd cloud_checker || { echo "ERROR: cloud_checker folder not found"; exit 1; }

pip install -r requirements_cloud.txt

echo "Launching proxy checker..."
exec python cloud_proxy_checker.py
