#!/usr/bin/env python3

# ========= AUTO-BOOTSTRAP =========
import os, sys, subprocess

def ensure_environment_ready():
    def need_bootstrap():
        try:
            import boto3, ssl  # noqa
        except Exception:
            return True

        # SSL חייב להיות קיים לפני שמרימים HTTPS
        if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
            return True

        return False

    if not need_bootstrap():
        return

    print("⚠ Environment not ready — running starter.sh...")

    if not os.path.exists("starter.sh"):
        print("❌ starter.sh missing — cannot auto-setup")
        sys.exit(1)

    subprocess.run(["bash", "starter.sh"], check=True)

    # מריץ את אותו תהליך מחדש אחרי שהסביבה מוכנה
    os.execv(sys.executable, [sys.executable] + sys.argv)

ensure_environment_ready()
# ==================================

import http.server, socketserver, urllib.parse, cgi
import boto3, ssl, json

PORT = 443
CONFIG_FILE = "app_config.json"


# ---------- CONFIG ----------
def load_config():
    return json.load(open(CONFIG_FILE)) if os.path.exists(CONFIG_FILE) else {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def build_s3(cfg):
    return boto3.client(
        "s3",
        aws_access_key_id=cfg["aws"]["access_key"],
        aws_secret_access_key=cfg["aws"]["secret_key"],
        region_name=cfg["aws"]["region"]
    )


config = load_config()
s3 = build_s3(config) if config.get("aws") else None


# ---------- HTTP HANDLER ----------
class UploadHandler(http.server.BaseHTTPRequestHandler):

    # ===== CSS מקצועי + Light/Dark =====
    def css(self):
        return """
        <style>
        :root {
          --bg: #020617;
          --bg-card: #020617;
          --bg-elevated: #030712;
          --border-subtle: #1f2937;
          --accent: #2563eb;
          --accent-soft: #1d4ed8;
          --danger: #b91c1c;
          --danger-soft: #7f1d1d;
          --text: #e5e7eb;
          --text-muted: #6b7280;
          --text-soft: #94a3b8;
        }
        body[data-theme="light"] {
          --bg: #f3f4f6;
          --bg-card: #ffffff;
          --bg-elevated: #ffffff;
          --border-subtle: #e5e7eb;
          --accent: #2563eb;
          --accent-soft: #1d4ed8;
          --danger: #dc2626;
          --danger-soft: #fee2e2;
          --text: #0f172a;
          --text-muted: #6b7280;
          --text-soft: #9ca3af;
        }
        body {
          margin:0;
          background: var(--bg);
          color: var(--text);
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        .top {
          background: var(--bg-elevated);
          border-bottom: 1px solid var(--border-subtle);
          padding: 18px 28px;
          font-size: 18px;
          font-weight: 600;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .top .right-actions {
          display:flex;
          gap:8px;
          align-items:center;
        }
        .chip {
          font-size: 12px;
          padding:4px 8px;
          border-radius:999px;
          border:1px solid var(--border-subtle);
          background: rgba(15,23,42,0.7);
        }
        body[data-theme="light"] .chip {
          background: #eef2ff;
        }
        .top button, .top a {
          border-radius: 999px;
          border: 1px solid var(--border-subtle);
          padding: 7px 12px;
          background: transparent;
          color: var(--text-soft);
          font-size: 13px;
          cursor:pointer;
          text-decoration:none;
        }
        .top a.danger {
          border-color: var(--danger);
          color: var(--danger);
        }
        .wrap {
          max-width: 1100px;
          margin: 26px auto;
          padding: 0 12px 40px;
        }
        .card {
          background: var(--bg-card);
          border-radius: 18px;
          border: 1px solid var(--border-subtle);
          padding: 24px 24px 26px;
          box-shadow: 0 18px 40px rgba(0,0,0,0.45);
        }
        h2 {
          margin-top:0;
          font-size:20px;
        }
        .subtitle {
          font-size: 13px;
          color: var(--text-muted);
          margin-bottom: 18px;
        }
        .input {
          width:100%;
          padding: 10px 11px;
          border-radius: 10px;
          border:1px solid var(--border-subtle);
          background: transparent;
          color: var(--text);
          font-size: 14px;
        }
        .input:focus {
          outline:none;
          border-color: var(--accent);
          box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent);
        }
        .btn {
          padding: 8px 14px;
          border-radius: 10px;
          border:0;
          background: var(--accent);
          color:#fff;
          font-weight:600;
          cursor:pointer;
          font-size:14px;
        }
        .btn.secondary {
          background: transparent;
          border:1px solid var(--border-subtle);
          color: var(--text-soft);
        }
        .btn.danger {
          background: var(--danger);
        }
        table {
          width:100%;
          border-collapse: collapse;
          margin-top: 14px;
        }
        th, td {
          padding: 10px 4px;
          border-bottom: 1px solid var(--border-subtle);
          font-size: 13px;
        }
        th {
          color: var(--text-soft);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          font-size: 11px;
        }
        td.size {
          color: var(--text-muted);
          white-space: nowrap;
        }
        td.actions {
          text-align:right;
          white-space: nowrap;
        }
        .link {
          font-size: 13px;
          color: var(--accent);
          text-decoration:none;
          margin-left: 8px;
        }
        .link.danger {
          color: var(--danger);
        }
        .tag-folder {
          display:inline-flex;
          align-items:center;
          gap:6px;
        }
        .folder-icon {
          width:16px;height:12px;
          border-radius:3px;
          background: linear-gradient(135deg,#f59e0b,#f97316);
        }
        body[data-theme="dark"] .folder-icon {
          background: linear-gradient(135deg,#facc15,#f97316);
        }
        .muted {
          color: var(--text-muted);
        }
        .upload-row {
          display:flex;
          flex-wrap:wrap;
          gap:10px;
          align-items:center;
          justify-content:space-between;
          margin-top: 18px;
        }
        .uploadbox {
          border-radius: 14px;
          border:1px dashed var(--border-subtle);
          padding: 14px 16px;
          background: rgba(15,23,42,0.6);
        }
        body[data-theme="light"] .uploadbox {
          background: #f9fafb;
        }
        .folder-form {
          margin-top:18px;
          display:flex;
          gap:8px;
          flex-wrap:wrap;
          align-items:center;
        }
        .search-row {
          display:flex;
          justify-content:space-between;
          align-items:center;
          gap:12px;
          margin-top: 8px;
        }
        .search-row .search {
          flex:1;
        }
        .badge-prefix {
          font-size:12px;
          color: var(--text-soft);
        }
        .progress-wrap {
          margin-top: 10px;
        }
        .progress-bar {
          width:100%;
          height:8px;
          border-radius:999px;
          background: rgba(15,23,42,0.8);
          overflow:hidden;
        }
        body[data-theme="light"] .progress-bar {
          background:#e5e7eb;
        }
        .progress-fill {
          height:100%;
          width:0%;
          background: linear-gradient(90deg,#22c55e,#16a34a);
          transition: width .15s linear;
        }
        .progress-text {
          font-size:12px;
          margin-top:4px;
          color: var(--text-muted);
        }
        .empty {
          text-align:center;
          padding: 32px 0;
          color: var(--text-muted);
          font-size: 14px;
        }
        </style>
        """

    # ===== JS: Theme + Search + Upload progress =====
    def scripts(self):
        return """
        <script>
        function applyTheme() {
          var saved = localStorage.getItem('s3mgr-theme') || 'dark';
          document.body.setAttribute('data-theme', saved);
        }
        function toggleTheme() {
          var cur = document.body.getAttribute('data-theme') || 'dark';
          var next = cur === 'dark' ? 'light' : 'dark';
          document.body.setAttribute('data-theme', next);
          localStorage.setItem('s3mgr-theme', next);
        }
        function initSearch() {
          var box = document.getElementById('searchBox');
          if (!box) return;
          box.addEventListener('input', function() {
            var q = box.value.toLowerCase();
            var rows = document.querySelectorAll('#fileTable tbody tr[data-kind]');
            rows.forEach(function(r) {
              if (!q) {
                r.style.display = '';
                return;
              }
              var text = r.getAttribute('data-name') || '';
              r.style.display = text.toLowerCase().indexOf(q) !== -1 ? '' : 'none';
            });
          });
        }
        function initUpload() {
          var form = document.getElementById('uploadForm');
          if (!form) return;
          var bar = document.getElementById('progressFill');
          var wrap = document.getElementById('progressWrap');
          var txt = document.getElementById('progressText');
          form.addEventListener('submit', function(e) {
            e.preventDefault();
            var fileInput = document.getElementById('fileInput');
            if (!fileInput || !fileInput.files.length) {
              alert('Choose a file first');
              return;
            }
            wrap.style.display = 'block';
            bar.style.width = '0%';
            txt.textContent = '0%';

            var xhr = new XMLHttpRequest();
            xhr.open('POST', form.getAttribute('action') || '/', true);

            xhr.upload.onprogress = function(ev) {
              if (ev.lengthComputable) {
                var p = Math.round((ev.loaded / ev.total) * 100);
                bar.style.width = p + '%';
                txt.textContent = p + '%';
              }
            };
            xhr.onload = function() {
              if (xhr.status === 200) {
                txt.textContent = 'Done';
                setTimeout(function(){ window.location.reload(); }, 500);
              } else {
                txt.textContent = 'Error ' + xhr.status;
              }
            };
            xhr.onerror = function() {
              txt.textContent = 'Upload failed';
            };

            var fd = new FormData(form);
            xhr.send(fd);
          });
        }
        document.addEventListener('DOMContentLoaded', function() {
          applyTheme();
          var themeBtn = document.getElementById('themeToggle');
          if (themeBtn) {
            themeBtn.addEventListener('click', function(e) {
              e.preventDefault();
              toggleTheme();
            });
          }
          initSearch();
          initUpload();
        });
        </script>
        """

    def respond(self, html):
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    # ===== GET =====
    def do_GET(self):
        global config, s3

        # אין bucket עדיין
        if not config.get("bucket"):
            html = f"""
            <html><head>{self.css()}{self.scripts()}</head>
            <body data-theme="dark">
              <div class='wrap'>
                <div class='card' style='max-width:480px;margin-top:40px'>
                  <h2>Connect a Bucket</h2>
                  <div class='subtitle'>Enter the S3 bucket name to manage files.</div>
                  <form method='post' action='/save-bucket'>
                    <input class='input' name='bucket' placeholder='bucket-name'><br><br>
                    <button class='btn'>Continue</button>
                  </form>
                </div>
              </div>
            </body></html>
            """
            return self.respond(html)

        # אין credentials
        if not config.get("aws") or not s3:
            html = f"""
            <html><head>{self.css()}{self.scripts()}</head>
            <body data-theme="dark">
              <div class='wrap'>
                <div class='card' style='max-width:480px;margin-top:40px'>
                  <h2>AWS Credentials</h2>
                  <div class='subtitle'>Access key is stored locally on this server only.</div>
                  <form method='post' action='/save-creds'>
                    <input class='input' name='access_key' placeholder='Access Key'><br><br>
                    <input class='input' name='secret_key' placeholder='Secret Key'><br><br>
                    <input class='input' name='region' value='us-east-1'><br><br>
                    <button class='btn'>Save</button>
                  </form>
                </div>
              </div>
            </body></html>
            """
            return self.respond(html)

        p = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(p.query)
        prefix = q.get("prefix", [""])[0]

        if p.path == "/change-bucket":
            config.pop("bucket", None)
            save_config(config)
            return self.respond("<script>location='/'</script>")

        if p.path == "/change-creds":
            config.pop("aws", None)
            save_config(config)
            return self.respond("<script>location='/'</script>")

        if p.path == "/download":
            try:
                key = q.get("file", [""])[0]
                local = f"/tmp/{os.path.basename(key)}"
                s3.download_file(config["bucket"], key, local)
                return self.respond(f"<html><body>Downloaded to {local}</body></html>")
            except Exception:
                return self.respond("<html><body>Download failed</body></html>")

        if p.path == "/delete":
            try:
                key = q.get("file", [""])[0]
                s3.delete_object(Bucket=config["bucket"], Key=key)
                return self.respond("<script>location='/'</script>")
            except Exception:
                return self.respond("<html><body>Delete failed</body></html>")

        # ===== LIST (עם תיקיות) =====
        try:
            resp = s3.list_objects_v2(
                Bucket=config["bucket"],
                Prefix=prefix if prefix else "",
                Delimiter="/"
            )
        except Exception:
            resp = {}

        folders = [cp["Prefix"] for cp in resp.get("CommonPrefixes", [])]
        files = [o for o in resp.get("Contents", []) if o["Key"] != prefix]

        folder_rows = ""
        for pref in folders:
            name = pref[len(prefix):].strip("/")
            folder_rows += f"""
            <tr data-kind="folder" data-name="{name}">
              <td>
                <span class='tag-folder'>
                  <span class='folder-icon'></span>
                  <span>{name}</span>
                </span>
              </td>
              <td class='size'>Folder</td>
              <td class='actions'>
                <a class='link' href='/?prefix={urllib.parse.quote(pref)}'>Open</a>
                <a class='link danger' href='/delete?file={urllib.parse.quote(pref)}'>Delete</a>
              </td>
            </tr>
            """

        file_rows = ""
        for o in files:
            name = o["Key"][len(prefix):] if prefix and o["Key"].startswith(prefix) else o["Key"]
            file_rows += f"""
            <tr data-kind="file" data-name="{name}">
              <td>{name}</td>
              <td class='size'>{o['Size']:,} bytes</td>
              <td class='actions'>
                <a class='link' href='/download?file={urllib.parse.quote(o["Key"])}'>Download</a>
                <a class='link danger' href='/delete?file={urllib.parse.quote(o["Key"])}'>Delete</a>
              </td>
            </tr>
            """

        rows = folder_rows + file_rows
        if not rows:
            rows = "<tr><td colspan='3' class='empty'>No files in this folder</td></tr>"

        prefix_label = "/" if not prefix else "/" + prefix.strip("/")

        html = f"""
        <html><head>{self.css()}{self.scripts()}</head>
        <body data-theme="dark">
          <div class='top'>
            <div>
              S3 Manager
              <span class='chip'>{config['bucket']}</span>
            </div>
            <div class='right-actions'>
              <span class='badge-prefix'>{prefix_label}</span>
              <a href='/change-bucket'>Change Bucket</a>
              <a class='danger' href='/change-creds'>Change Credentials</a>
              <button id='themeToggle'>Light/Dark</button>
            </div>
          </div>

          <div class='wrap'>
            <div class='card'>
              <h2>Objects</h2>
              <div class='subtitle'>
                Browse, upload and manage files in your S3 bucket.
              </div>

              <div class='search-row'>
                <div class='search'>
                  <input id='searchBox' class='input' placeholder='Search files or folders...'>
                </div>
              </div>

              <table id='fileTable'>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Size</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {rows}
                </tbody>
              </table>

              <div class='uploadbox'>
                <form id='uploadForm' method='post' enctype='multipart/form-data'>
                  <div class='upload-row'>
                    <div>
                      <input id='fileInput' type='file' name='file'>
                      <input type='hidden' name='prefix' value='{prefix}'>
                    </div>
                    <div>
                      <button class='btn'>Upload</button>
                    </div>
                  </div>
                  <div id='progressWrap' class='progress-wrap' style='display:none'>
                    <div class='progress-bar'>
                      <div id='progressFill' class='progress-fill'></div>
                    </div>
                    <div id='progressText' class='progress-text'>0%</div>
                  </div>
                </form>

                <form class='folder-form' method='post' action='/create-folder'>
                  <input type='hidden' name='prefix' value='{prefix}'>
                  <input class='input' style='max-width:220px' name='folder' placeholder='New folder name'>
                  <button class='btn secondary' type='submit'>Create Folder</button>
                </form>
              </div>
            </div>
          </div>
        </body></html>
        """
        self.respond(html)

    # ===== POST =====
    def do_POST(self):
        global config, s3

        if self.path == "/save-bucket":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            bucket = form.get("bucket", [""])[0].strip()
            if bucket:
                config["bucket"] = bucket
                save_config(config)
            return self.respond("<script>location='/'</script>")

        if self.path == "/save-creds":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            config["aws"] = {
                "access_key": form.get("access_key", [""])[0],
                "secret_key": form.get("secret_key", [""])[0],
                "region": form.get("region", ["us-east-1"])[0],
            }
            save_config(config)
            global s3
            s3 = build_s3(config)
            return self.respond("<script>location='/'</script>")

        if self.path == "/create-folder":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            prefix = form.get("prefix", [""])[0]
            name = form.get("folder", [""])[0].strip()
            if name:
                if not name.endswith("/"):
                    name += "/"
                key = (prefix or "") + name
                s3.put_object(Bucket=config["bucket"], Key=key, Body=b"")
            return self.respond("<script>location='/'</script>")

        # upload (כולל prefix)
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST"}
            )
            file_item = form["file"]
            prefix = ""
            if "prefix" in form and form["prefix"].value:
                prefix = form["prefix"].value
            if prefix and not prefix.endswith("/"):
                prefix = prefix + "/"
            key = (prefix or "") + file_item.filename
            s3.upload_fileobj(file_item.file, config["bucket"], key)
            return self.respond("<script>location='/'</script>")
        except Exception as e:
            return self.respond(f"<html><body>Upload failed: {e}</body></html>")


# ---------- HTTPS SERVER ----------
with socketserver.TCPServer(("", PORT), UploadHandler) as httpd:
    print(f"Serving S3 manager on port {PORT} (HTTPS)")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain("cert.pem", "key.pem")
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd.serve_forever()
