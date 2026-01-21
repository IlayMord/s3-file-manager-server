#!/bin/bash
set -e

echo "===> Updating system..."
sudo apt update -y
sudo apt install -y python3-venv unzip curl

echo "===> Creating venv..."
python3 -m venv .venv
source .venv/bin/activate

echo "===> Installing Python deps..."
pip install --upgrade pip
pip install boto3 botocore

[[ -f requirements.txt ]] && pip install -r requirements.txt || true

echo "✔ Environment ready"
