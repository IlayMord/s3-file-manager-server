#!/bin/bash
set -e

echo "===> Updating system..."
sudo apt update -y
sudo apt install -y python3-venv unzip curl openssl

echo "===> Creating venv..."
python3 -m venv .venv
source .venv/bin/activate

echo "===> Installing Python deps..."
pip install --upgrade pip
pip install boto3 botocore

[[ -f requirements.txt ]] && pip install -r requirements.txt || true

echo "===> Checking SSL certs..."
if [[ ! -f cert.pem || ! -f key.pem ]]; then
  openssl req -newkey rsa:2048 -nodes \
    -keyout key.pem -x509 -days 365 \
    -out cert.pem -subj "/C=IL/ST=None/L=None/O=Server/CN=localhost"
  chmod 600 key.pem
fi

echo "✔ Environment ready"
