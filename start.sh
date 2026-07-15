#!/usr/bin/env bash
set -e

echo "============================================"
echo " Cloud Proxy Checker — Render Startup"
echo "============================================"

cd cloud_checker || { echo "cloud_checker directory not found"; exit 1; }

# Install dependencies
pip install -r requirements_cloud.txt

# Launch the checker
exec python cloud_proxy_checker.py