#!/usr/bin/env python3
import http.server, socketserver, urllib.parse, cgi
import boto3, os, ssl, json, subprocess

PORT = 443
CONFIG_FILE = "app_config.json"


# --------------------------
#  BOOTSTRAP
# --------------------------

def ensure_aws_cli():
    try:
        subprocess.run(["aws","--version"],check=True)
        print("✔ AWS CLI is installed")
    except Exception:
        print("⚠ AWS CLI missing — running starter.sh...")
        subprocess.run(["bash","starter.sh"],check=True)

def ensure_ssl_cert():
    if not (os.path.exists("cert.pem") and os.path.exists("key.pem")):
        print("⚠ SSL certificate missing — generating...")
        subprocess.run([
            "openssl","req","-newkey","rsa:2048","-nodes",
            "-keyout","key.pem",
            "-x509","-days","365",
            "-out","cert.pem",
            "-subj","/C=IL/ST=None/L=None/O=Server/CN=localhost"
        ],check=True)
        os.chmod("key.pem",0o600)
        print("✔ cert.pem + key.pem created")
    else:
        print("✔ SSL certificate exists")

ensure_aws_cli()
ensure_ssl_cert()


# --------------------------
#  CONFIG + CLIENT
# --------------------------

def load_config():
    return json.load(open(CONFIG_FILE)) if os.path.exists(CONFIG_FILE) else None

def save_config(data):
    with open(CONFIG_FILE,"w") as f:
        json.dump(data,f)

def build_s3_client(cfg):
    return boto3.client(
        "s3",
        aws_access_key_id=cfg["aws"]["access_key"],
        aws_secret_access_key=cfg["aws"]["secret_key"],
        region_name=cfg["aws"]["region"]
    )

config = load_config()
s3 = build_s3_client(config) if config and "aws" in config else None


# --------------------------
#  HTTP HANDLER
# --------------------------

class UploadHandler(http.server.BaseHTTPRequestHandler):

    # ---------- UI STYLE ----------
    def css(self):
        return """
        <style>
        body{margin:0;background:#0f172a;font-family:Inter,Arial;color:#e5e7eb}
        .topbar{background:#020617;padding:16px 26px;font-weight:600;border-bottom:1px solid #1f2937}
        .card{background:#111827;border:1px solid #1f2937;padding:28px;border-radius:16px;
              width:1000px;margin:30px auto;box-shadow:0 30px 80px rgba(0,0,0,.55)}
        .btn{padding:10px 14px;border-radius:10px;border:0;font-weight:600;cursor:pointer;
             background:linear-gradient(135deg,#2563eb,#06b6d4);color:white;text-decoration:none}
        .danger{background:#dc2626}
        table{width:100%;border-collapse:collapse;margin-top:10px}
        th,td{padding:12px;border-bottom:1px solid #1f2937}
        th{color:#94a3b8;font-size:13px;text-align:left}
        .actions{text-align:right}
        .uploadbox{margin-top:20px;border:1px dashed #334155;padding:18px;border-radius:14px;text-align:center}
        input{color:#e5e7eb}
        /* popup overlay */
        .overlay{position:fixed;inset:0;background:#00000099;display:none;align-items:center;justify-content:center}
        .popup{background:#020617;border:1px solid #1f2937;padding:22px 26px;border-radius:14px;width:360px;
               box-shadow:0 20px 80px rgba(0,0,0,.6);text-align:center}
        .popup h3{margin-top:0}
        .closebtn{margin-top:12px;background:#334155}
        .ok{background:#22c55e}
        </style>
        """

    # ---------- POPUP TEMPLATE ----------
    def popup_js(self):
        return """
        <script>
        function showPopup(title,msg){
          const box=document.getElementById("popup-box");
          document.getElementById("p-title").innerText=title;
          document.getElementById("p-msg").innerText=msg;
          box.style.display="flex";
        }
        function closePopup(){
          document.getElementById("popup-box").style.display="none";
          window.location.reload();
        }
        </script>
        """

    # ---------- SAFE RESPONSE ----------
    def respond(self, html):
        self.send_response(200)
        self.send_header("Content-Type","text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    # ---------- FILE LIST ----------
    def list_objects(self):
        try:
            objects = s3.list_objects_v2(Bucket=config["bucket"])
            files = objects.get("Contents", [])
        except Exception:
            return """
            <tr><td colspan='3' style='text-align:center;color:#ef4444'>
              Bucket not found — choose another bucket<br><br>
              <a class='btn' href='/change-bucket'>Change Bucket</a>
            </td></tr>
            """

        if not files:
            return "<tr><td colspan='3' style='text-align:center;color:#6b7280'>No files</td></tr>"

        rows = ""
        for obj in files:
            name = obj["Key"]; size = obj["Size"]
            rows += f"""
            <tr>
              <td>{name}</td>
              <td>{size:,} bytes</td>
              <td class="actions">
                <a class="btn" href="/download?file={urllib.parse.quote(name)}">Download</a>
                <a class="btn danger" href="/delete?file={urllib.parse.quote(name)}">Delete</a>
              </td>
            </tr>
            """
        return rows

    # ---------- PAGES ----------
    def render_bucket_page(self):
        html = f"""
        <html><head><meta charset='utf-8'><title>Select Bucket</title>
        {self.css()}</head><body>

        <div class='card' style='width:460px'>
          <h2>Select Bucket</h2>
          <form method='post' action='/save-bucket'>
            <input name='bucket' placeholder='bucket-name'><br><br>
            <button class='btn'>Continue</button>
          </form>
        </div>

        </body></html>
        """
        self.respond(html)

    def render_creds_page(self):
        html = f"""
        <html><head><meta charset='utf-8'><title>AWS Credentials</title>
        {self.css()}</head><body>

        <div class='card' style='width:460px'>
          <h2>Configure AWS Credentials</h2>
          <form method='post' action='/save-creds'>
            <input name='access_key' placeholder='Access Key'><br><br>
            <input name='secret_key' placeholder='Secret Key'><br><br>
            <input name='region' value='us-east-1'><br><br>
            <button class='btn'>Save</button>
          </form>
        </div>

        </body></html>
        """
        self.respond(html)

    # ---------- GET ----------
    def do_GET(self):
        global config, s3

        if not config:
            return self.render_bucket_page()
        if "aws" not in config or not s3:
            return self.render_creds_page()

        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)

        # popup-based download
        if parsed.path == "/download":
            key = q.get("file",[""])[0]
            try:
                local = f"/tmp/{os.path.basename(key)}"
                s3.download_file(config["bucket"], key, local)
                self.respond(f"<script>alert('Downloaded to {local}');window.location='/'</script>")
            except Exception:
                self.respond("<script>alert('Bucket not found');window.location='/'</script>")
            return

        # popup-based delete
        if parsed.path == "/delete":
            key = q.get("file",[""])[0]
            try:
                s3.delete_object(Bucket=config["bucket"],Key=key)
                self.respond(f"<script>alert('File deleted');window.location='/'</script>")
            except Exception:
                self.respond("<script>alert('Bucket not found');window.location='/'</script>")
            return

        table_rows = self.list_objects()

        html = f"""
        <html><head><meta charset='utf-8'><title>S3 Manager</title>
        {self.css()}{self.popup_js()}</head>
        <body>

        <div class="topbar">
          S3 Manager — {config['bucket']}
          &nbsp;&nbsp;
          <a class="btn" href="/change-bucket">Change Bucket</a>
          <a class="btn danger" href="/change-creds">Change Credentials</a>
        </div>

        <div class="card">
          <h2>Files</h2>

          <table>
            <tr><th>Name</th><th>Size</th><th></th></tr>
            {table_rows}
          </table>

          <div class="uploadbox">
            <form method="post" enctype="multipart/form-data">
              <input type="file" name="file"><br><br>
              <button class="btn">Upload</button>
            </form>
          </div>
        </div>

        <!-- Popup -->
        <div id="popup-box" class="overlay">
          <div class="popup">
            <h3 id="p-title"></h3>
            <div id="p-msg"></div>
            <button class="btn ok" onclick="closePopup()">OK</button>
          </div>
        </div>

        </body></html>
        """
        self.respond(html)

    # ---------- POST ----------
    def do_POST(self):
        global config, s3

        if self.path == "/save-bucket":
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            form = urllib.parse.parse_qs(body)
            config = {"bucket": form["bucket"][0]}
            save_config(config)
            self.respond("<script>window.location='/'</script>")
            return

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
            self.respond("<script>window.location='/'</script>")
            return

        # upload with popup
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,headers=self.headers,
                environ={"REQUEST_METHOD":"POST"}
            )
            s3.upload_fileobj(
                form["file"].file,
                config["bucket"],
                form["file"].filename
            )
            self.respond("<script>alert('Upload complete');window.location='/'</script>")
        except Exception:
            self.respond("<script>alert('Upload failed — bucket not found');window.location='/'</script>")


# --------------------------
#  HTTPS SERVER
# --------------------------

with socketserver.TCPServer(("",PORT),UploadHandler) as httpd:
    print(f"Serving S3 manager on port {PORT} (HTTPS)")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain("cert.pem","key.pem")
    httpd.socket = ctx.wrap_socket(httpd.socket,server_side=True)
    httpd.serve_forever()
