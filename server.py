#!/usr/bin/env python3
import http.server
import socketserver
import urllib.parse
import cgi
import boto3
import os
import ssl
import shutil
import subprocess


PORT = 443
BUCKET = "ilay-bucket1"


# --------------------------
#  BOOTSTRAP (AWS + SSL)
# --------------------------

def ensure_aws_cli():
    try:
        subprocess.run(["aws", "--version"], check=True)
        print("✔ AWS CLI is installed")
    except Exception:
        print("⚠ AWS CLI missing — running starter.sh...")
        subprocess.run(["bash", "starter.sh"], check=True)


def ensure_ssl_cert():
    if not (os.path.exists("cert.pem") and os.path.exists("key.pem")):
        print("⚠ SSL certificate missing — generating...")
        subprocess.run([
            "openssl","req","-newkey","rsa:2048","-nodes",
            "-keyout","key.pem",
            "-x509","-days","365",
            "-out","cert.pem",
            "-subj","/C=IL/ST=None/L=None/O=Server/CN=localhost"
        ], check=True)
        os.chmod("key.pem", 0o600)
        print("✔ cert.pem + key.pem created")
    else:
        print("✔ SSL certificate exists")


ensure_aws_cli()
ensure_ssl_cert()


# --------------------------
#  S3 CLIENT
# --------------------------

s3 = boto3.client("s3")


# --------------------------
#  HTTP HANDLER
# --------------------------

class UploadHandler(http.server.BaseHTTPRequestHandler):

    def list_objects(self):
        objects = s3.list_objects_v2(Bucket=BUCKET)
        files = objects.get("Contents", [])
        rows = ""

        for obj in files:
            name = obj["Key"]
            size = obj["Size"]

            rows += f"""
            <tr>
              <td>{name}</td>
              <td>{size:,} bytes</td>
              <td class="actions">
                <a class="btn download" href="/download?file={urllib.parse.quote(name)}">⬇ Download</a>
                <a class="btn delete" href="/delete?file={urllib.parse.quote(name)}">🗑 Delete</a>
              </td>
            </tr>
            """

        return rows or "<tr><td colspan='3' class='empty'>Bucket is empty</td></tr>"


    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        # ---- DOWNLOAD ----
        if parsed.path == "/download":
            key = query.get("file", [""])[0]
            if not key:
                self.send_error(400, "Missing file parameter")
                return

            local_path = f"/tmp/{os.path.basename(key)}"
            try:
                s3.download_file(BUCKET, key, local_path)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Downloaded to {local_path}".encode())
            except Exception as e:
                self.send_error(500, str(e))
            return

        # ---- DELETE ----
        if parsed.path == "/delete":
            key = query.get("file", [""])[0]
            if not key:
                self.send_error(400, "Missing file parameter")
                return

            try:
                s3.delete_object(Bucket=BUCKET, Key=key)
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
            except Exception as e:
                self.send_error(500, str(e))
            return

        # ---- MAIN PAGE ----
        table_rows = self.list_objects()

        html = f"""
        <html>
        <head>
        <meta charset="utf-8">
        <title>S3 File Manager</title>

        <style>
            body {{
              font-family: Arial, Helvetica, sans-serif;
              background: linear-gradient(135deg, #2F80ED, #56CCF2);
              margin: 0;
              padding: 0;
              color: #333;
            }}

            .container {{
              max-width: 900px;
              margin: 40px auto;
              background: #fff;
              border-radius: 12px;
              padding: 30px;
              box-shadow: 0 15px 40px rgba(0,0,0,0.15);
            }}

            h2 {{
              text-align: center;
              color: #2F80ED;
              margin-top: 0;
            }}

            table {{
              width: 100%;
              border-collapse: collapse;
              margin-top: 15px;
            }}

            th, td {{
              padding: 12px;
              border-bottom: 1px solid #eee;
            }}

            tr:hover {{
              background: #f7faff;
            }}

            .actions {{
              text-align:right;
            }}

            .btn {{
              padding: 7px 12px;
              border-radius: 6px;
              text-decoration: none;
              font-size: 13px;
              font-weight: 600;
              margin-left: 6px;
            }}

            .download {{ background:#2F80ED; color:white; }}
            .delete {{ background:#EB5757; color:white; }}

            .upload-box {{
              margin-top: 25px;
              padding: 20px;
              border: 1px dashed #aaa;
              border-radius: 10px;
              text-align:center;
              background:#fafafa;
            }}

            .upload-btn {{
              background:#27AE60;
              color:white;
              padding:10px 18px;
              border:none;
              border-radius:6px;
              cursor:pointer;
            }}
        </style>
        </head>

        <body>
        <div class="container">

          <h2>S3 File Manager — {BUCKET}</h2>

          <table>
            <tr>
              <th>File name</th>
              <th>Size</th>
              <th></th>
            </tr>
            {table_rows}
          </table>

          <div class="upload-box">
            <h3>Upload new file</h3>
            <form enctype="multipart/form-data" method="post">
              <input type="file" name="file"><br><br>
              <button class="upload-btn">Upload</button>
            </form>
          </div>

        </div>
        </body>
        </html>
        """

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())


    def do_POST(self):
        try:
            ctype, _ = cgi.parse_header(self.headers.get("Content-Type"))
            if ctype != "multipart/form-data":
                self.send_error(400, "Invalid form")
                return

            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST"}
            )

            file_field = form["file"]
            filename = file_field.filename

            if not filename:
                self.send_error(400, "No file selected")
                return

            s3.upload_fileobj(file_field.file, BUCKET, filename)

            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()

        except Exception as e:
            self.send_error(500, str(e))



# --------------------------
#  HTTPS SERVER
# --------------------------

with socketserver.TCPServer(("", PORT), UploadHandler) as httpd:
    print(f"Serving S3 manager on port {PORT} (HTTPS)")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    httpd.serve_forever()
