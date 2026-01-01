#!/usr/bin/env python3

# ========= AUTO-BOOTSTRAP =========
import os, sys, subprocess

def ensure_environment_ready():
    try:
        import boto3  # noqa
        import ssl    # noqa
    except Exception:
        print("⚠ Environment not ready — running starter.sh...")

        if not os.path.exists("starter.sh"):
            print("❌ starter.sh missing — cannot auto-setup")
            sys.exit(1)

        subprocess.run(["bash", "starter.sh"], check=True)

        # reload process after setup
        os.execv(sys.executable, [sys.executable] + sys.argv)

ensure_environment_ready()
# ==================================


import http.server, socketserver, urllib.parse, cgi
import boto3, ssl, json


PORT = 443
CONFIG_FILE = "app_config.json"


# ---------- CONFIG ----------
def load_config():
    return json.load(open(CONFIG_FILE)) if os.path.exists(CONFIG_FILE) else None

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)

def build_s3_client(cfg):
    return boto3.client(
        "s3",
        aws_access_key_id=cfg["aws"]["access_key"],
        aws_secret_access_key=cfg["aws"]["secret_key"],
        region_name=cfg["aws"]["region"]
    )


config = load_config()
s3 = build_s3_client(config) if config and "aws" in config else None


# ---------- HTTP HANDLER ----------
class UploadHandler(http.server.BaseHTTPRequestHandler):

    # ===== CSS =====
    def css(self):
        return """
        <style>
        body{margin:0;background:#0f172a;font-family:Arial;color:#e5e7eb}
        .topbar{background:#020617;padding:16px 26px;font-weight:600;
                border-bottom:1px solid #1f2937}
        .card{background:#111827;border:1px solid #1f2937;
              padding:28px;border-radius:16px;width:1000px;margin:30px auto}
        .btn{padding:9px 14px;border-radius:10px;border:0;font-weight:600;
             background:#2563eb;color:white;text-decoration:none}
        .danger{background:#dc2626}
        .uploadbox{margin-top:20px;border:1px dashed #334155;
                   padding:18px;border-radius:14px;text-align:center}
        table{width:100%;border-collapse:collapse;margin-top:10px}
        th,td{padding:12px;border-bottom:1px solid #1f2937}
        th{color:#94a3b8;font-size:13px;text-align:left}
        .actions{text-align:right}
        .overlay{position:fixed;inset:0;background:#0009;
                 display:none;align-items:center;justify-content:center}
        .popup{background:#020617;border:1px solid #1f2937;
               padding:20px 26px;border-radius:14px;width:360px;text-align:center}
        .ok{background:#22c55e}
        </style>
        """

    # ===== JS popups =====
    def popup_js(self):
        return """
        <script>
        function showPopup(t,m){
          document.getElementById("p-title").innerText=t;
          document.getElementById("p-msg").innerText=m;
          document.getElementById("popup").style.display="flex";
        }
        function closePopup(){
          document.getElementById("popup").style.display="none";
          window.location.reload();
        }
        </script>
        """

    def respond(self, html):
        self.send_response(200)
        self.send_header("Content-Type","text/html")
        self.end_headers()
        self.wfile.write(html.encode())


    # ===== BUCKET / CREDS PAGES =====
    def page_bucket(self):
        self.respond(f"""
        <html><head>{self.css()}</head><body>
        <div class='card' style='width:460px'>
          <h2>Select Bucket</h2>
          <form method='post' action='/save-bucket'>
            <input name='bucket' placeholder='bucket-name'><br><br>
            <button class='btn'>Continue</button>
          </form>
        </div></body></html>
        """)

    def page_creds(self):
        self.respond(f"""
        <html><head>{self.css()}</head><body>
        <div class='card' style='width:460px'>
          <h2>AWS Credentials</h2>
          <form method='post' action='/save-creds'>
            <input name='access_key' placeholder='Access Key'><br><br>
            <input name='secret_key' placeholder='Secret Key'><br><br>
            <input name='region' value='us-east-1'><br><br>
            <button class='btn'>Save</button>
          </form>
        </div></body></html>
        """)


    # ===== FILE LIST =====
    def list_objects(self):
        try:
            objects = s3.list_objects_v2(Bucket=config["bucket"])
            files = objects.get("Contents", [])
        except Exception:
            return """
            <tr><td colspan=3 style='text-align:center;color:#ef4444'>
              Bucket not found — choose another bucket<br><br>
              <a class='btn' href='/change-bucket'>Change Bucket</a>
            </td></tr>
            """

        if not files:
            return "<tr><td colspan=3 style='text-align:center;color:#6b7280'>No files</td></tr>"

        rows = ""
        for o in files:
            rows += f"""
            <tr>
              <td>{o['Key']}</td>
              <td>{o['Size']:,} bytes</td>
              <td class='actions'>
                <a class='btn' href='/download?file={urllib.parse.quote(o['Key'])}'>Download</a>
                <a class='btn danger' href='/delete?file={urllib.parse.quote(o['Key'])}'>Delete</a>
              </td>
            </tr>
            """
        return rows


    # ===== GET =====
    def do_GET(self):
        global config, s3

        if not config:
            return self.page_bucket()
        if "aws" not in config or not s3:
            return self.page_creds()

        p = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(p.query)

        if p.path == "/change-bucket":
            config.pop("bucket", None)
            save_config(config)
            return self.page_bucket()

        if p.path == "/change-creds":
            config.pop("aws", None)
            save_config(config)
            return self.page_creds()

        # download action
        if p.path == "/download":
            try:
                k = q.get("file",[""])[0]
                local = f"/tmp/{os.path.basename(k)}"
                s3.download_file(config["bucket"], k, local)
                return self.respond(f"<script>showPopup('Download complete','Saved to {local}')</script>")
            except Exception:
                return self.respond("<script>showPopup('Error','Bucket not found')</script>")

        # delete action
        if p.path == "/delete":
            try:
                k = q.get("file",[""])[0]
                s3.delete_object(Bucket=config["bucket"], Key=k)
                return self.respond("<script>showPopup('Deleted','File removed')</script>")
            except Exception:
                return self.respond("<script>showPopup('Error','Bucket not found')</script>")

        rows = self.list_objects()

        html = f"""
        <html><head>{self.css()}{self.popup_js()}</head><body>

        <div class='topbar'>
          S3 Manager — {config['bucket']}
          &nbsp;&nbsp;
          <a class='btn' href='/change-bucket'>Change Bucket</a>
          <a class='btn danger' href='/change-creds'>Change Credentials</a>
        </div>

        <div class='card'>
          <h2>Files</h2>

          <table>
            <tr><th>Name</th><th>Size</th><th></th></tr>
            {rows}
          </table>

          <div class='uploadbox'>
            <form method='post' enctype='multipart/form-data'>
              <input type='file' name='file'><br><br>
              <button class='btn'>Upload</button>
            </form>
          </div>
        </div>

        <div id='popup' class='overlay'>
          <div class='popup'>
            <h3 id='p-title'></h3>
            <div id='p-msg'></div><br>
            <button class='btn ok' onclick='closePopup()'>OK</button>
          </div>
        </div>

        </body></html>
        """
        self.respond(html)


    # ===== POST =====
    def do_POST(self):
        global config, s3

        if self.path == "/save-bucket":
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            form = urllib.parse.parse_qs(body)
            config = {"bucket": form["bucket"][0]}
            save_config(config)
            return self.respond("<script>window.location='/'</script>")

        if self.path == "/save-creds":
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            form = urllib.parse.parse_qs(body)
            config["aws"] = {
                "access_key": form["access_key"][0],
                "secret_key": form["secret_key"][0],
                "region": form["region"][0]
            }
            save_config(config)
            s3 = build_s3_client(config)
            return self.respond("<script>window.location='/'</script>")

        try:
            form = cgi.FieldStorage(
                fp=self.rfile, headers=self.headers,
                environ={"REQUEST_METHOD":"POST"}
            )
            s3.upload_fileobj(form["file"].file, config["bucket"], form["file"].filename)
            return self.respond("<script>showPopup('Upload complete','File uploaded')</script>")
        except Exception:
            return self.respond("<script>showPopup('Upload failed','Bucket not found')</script>")


# ---------- HTTPS SERVER ----------
with socketserver.TCPServer(("", PORT), UploadHandler) as httpd:
    print(f"Serving S3 manager on port {PORT} (HTTPS)")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain("cert.pem","key.pem")
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd.serve_forever()
