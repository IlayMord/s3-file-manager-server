**S3 File Manager (HTTPS Python Server)**

A lightweight Python server that lets you manage files in an AWS S3 bucket through a simple web page.
You can view files, upload new files, download files, and delete files.
The server runs over HTTPS on port 443 using a local SSL certificate.

Project Files
• server.py — the HTTPS S3 file-manager server
• starter.sh — setup script that creates the SSL certificate and installs AWS CLI

Requirements
• Linux (Ubuntu / Debian recommended)
• Python 3.9 or higher
• sudo permissions
• AWS credentials with S3 access
• boto3 installed (pip install boto3)

Configuration
At the top of server.py set:
PORT = 443
BUCKET = "ilay-bucket1"

Running the Setup Script
chmod +x starter.sh
./starter.sh

The script creates:
• cert.pem
• key.pem
Both files must remain in the same folder as server.py

Running the Server
sudo python3 server.py

Opening the Web Page
https://<server-ip>/

What You Get
• File list from the S3 bucket
• Upload option
• Download and delete actions

Notes
• A self-signed certificate may show a browser warning
• For public use, it is recommended to add authentication and use a trusted TLS certificate
