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

echo "===> Checking AWS CLI..."
if ! command -v aws >/dev/null 2>&1; then
  curl -O https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
  unzip -o awscli-exe-linux-x86_64.zip
  sudo ./aws/install
  sudo ln -sf /usr/local/aws-cli/v2/current/bin/aws /usr/local/bin/aws || true
  rm -rf aws awscli-exe-linux-x86_64.zip
fi

echo "===> Allowing Python to bind port 443 (no sudo needed)..."
sudo setcap 'cap_net_bind_service=+ep' "$(readlink -f .venv/bin/python3)" || true

echo "===> Verifying server file..."
if [[ ! -f server.py ]]; then
  echo "❌ server.py not found in this directory"
  exit 1
fi

echo "===> Starting server on HTTPS:443..."
.venv/bin/python3 server.py &
SERVER_PID=$!

echo "✔ Environment ready — server is running (pid: $SERVER_PID)"
echo "👉 To stop it: kill $SERVER_PID"
