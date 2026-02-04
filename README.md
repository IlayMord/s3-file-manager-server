# S3 File Manager 🚀

A lightweight Python web UI for browsing and managing files in an Amazon S3 bucket.
Runs locally and stores configuration on the server.

## ✨ Features
- Web UI for listing, uploading (multi-file), downloading, deleting, and creating folders
- Prefix navigation with breadcrumbs
- Search with server-side pagination
- Sort and grid/list view toggle
- Copy S3 URIs to clipboard
- Upload progress bar and drag-and-drop support
- Preview for common file types (images, video, audio, text, PDF)
- Share links via pre-signed URLs
- Bulk actions (move, copy, delete) and rename
- Email/password authentication with server-side sessions (Postgres)
- AWS credentials are stored encrypted on disk

## ✅ Requirements
- Python 3.8+ (Docker image uses 3.11)
- PostgreSQL (for users/sessions/app settings)
- AWS credentials with access to the target S3 bucket
- Existing S3 bucket

## 📦 Install (Local)
```bash
python3 -m pip install -r app/requirements.txt
```

## ▶️ Run (Local)
```bash
python3 app/server.py
```

Then open `http://localhost:80` in your browser (or the port you set).

### Local env vars
- `S3FM_DB_URL` (default: `postgresql://postgres:postgres@localhost:5432/s3_file_manager`)

## 🐳 Docker
Build and run with compose:
```bash
docker compose -f docker/docker-compose.yml up -d --build
```

Stop:
```bash
docker compose -f docker/docker-compose.yml down
```

The compose file includes PostgreSQL and wires `S3FM_DB_URL` automatically.

## ☁️ Terraform (NLB + ASG Auto Deploy)
This repo includes Terraform modules that create a VPC + Network Load Balancer
and an Auto Scaling Group. The ASG uses user-data to clone this repo and start
the Docker container.

### Steps
1) Configure AWS credentials locally.
2) Set your SSH key pair name in `terraform/variables.tf` (`key_name`).
3) Run Terraform:
```bash
cd terraform
terraform init
terraform apply
```
4) When it finishes, grab the NLB DNS name:
```bash
terraform output nlb_dns_name
```
5) Open in your browser:
```
http://<NLB_DNS_NAME>
```

### What user-data does
- Installs Docker + Docker Compose
- Clones this repository
- Runs `docker-compose up -d` from `docker/`

### Modules
- `terraform/modules/vpc` creates the VPC, subnet, and security group.
- `terraform/modules/nlb` creates the Network Load Balancer and target group.
- `terraform/modules/asg` creates the Auto Scaling Group and injects user-data.

## ⚙️ Configuration
The app stores configuration in:
- `~/.s3-file-manager/app_config.json` (preferred)
- `/tmp/s3-file-manager/app_config.json` (fallback)

You can override paths/ports with environment variables:
- `S3FM_PORT` (default: `80`)
- `S3FM_CONFIG_DIR`
- `S3FM_DB_URL`

## 🔐 Encryption
AWS access keys are encrypted before being written to the config file.
The encryption key is stored locally at:
- `<S3FM_CONFIG_DIR>/secret.key`

Keep this file safe. If you delete it, existing encrypted credentials
cannot be decrypted.

## 📝 Notes
- `/download` streams to the browser. `/download-server` saves to `/tmp/<filename>` on the server host.
- Credentials are stored locally on the server and are encrypted.
- On first run, open `/register` to create a user and store AWS credentials.

## 🏗 Architecture Diagram

![Architecture Diagram](docs/architecture.png)

This diagram shows the full deployment architecture:
- Terraform provisions the AWS infrastructure (VPC, NLB, ASG, Security Group).
- ASG instances run Docker and Docker Compose.
- The application runs as a container and accesses Amazon S3 using an IAM Role.
- Users access the web UI via HTTP on port 80.
