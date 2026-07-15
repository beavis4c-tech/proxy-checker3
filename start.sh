#!/usr/bin/env bash
set -e

echo "============================================"
echo " Cloud Proxy Checker — Render Startup"
echo "============================================"

echo "Current directory contents:"
ls -la

pip install -r requirements_cloud.txt

echo "Launching proxy checker..."
exec python cloud_proxy_checker.py
