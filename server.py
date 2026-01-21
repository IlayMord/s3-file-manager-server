#!/usr/bin/env python3

# ========= AUTO-BOOTSTRAP =========
import os, sys, subprocess

def ensure_environment_ready():
    def need_bootstrap():
        try:
            import boto3
        except Exception:
            return True
        return False

    if not need_bootstrap():
        return

    print("⚠ Environment not ready — running setup.sh...")

    if not os.path.exists("setup.sh"):
        print("❌ setup.sh is missing — automatic setup cannot continue")
        sys.exit(1)

    subprocess.run(["bash", "setup.sh"], check=True)

    # Relaunch after environment is ready
    os.execv(sys.executable, [sys.executable] + sys.argv)

ensure_environment_ready()
# ==================================

import http.server, socketserver, urllib.parse, cgi
import boto3, ssl, json

def resolve_port():
    try:
        return int(os.getenv("S3MGR_PORT", "80"))
    except Exception:
        return 80


def resolve_config_dir():
    env_dir = os.getenv("S3MGR_CONFIG_DIR")
    if env_dir:
        return env_dir
    default_dir = os.path.join(os.path.expanduser("~"), ".s3-file-manager")
    try:
        os.makedirs(default_dir, exist_ok=True)
        if os.access(default_dir, os.W_OK | os.X_OK):
            return default_dir
    except Exception:
        pass
    return "/tmp/s3-file-manager"

PORT = resolve_port()
CONFIG_DIR = resolve_config_dir()
CONFIG_FILE = os.path.join(CONFIG_DIR, "app_config.json")
LEGACY_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "app_config.json")
CONFIG_ERROR = ""


# ---------- CONFIG ----------
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    if os.path.exists(LEGACY_CONFIG_FILE):
        try:
            with open(LEGACY_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def save_config(cfg):
    global CONFIG_ERROR, CONFIG_FILE
    CONFIG_ERROR = ""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        CONFIG_ERROR = str(e)
    fallback_dir = "/tmp/s3-file-manager"
    try:
        os.makedirs(fallback_dir, exist_ok=True)
        fallback_file = os.path.join(fallback_dir, "app_config.json")
        with open(fallback_file, "w") as f:
            json.dump(cfg, f, indent=2)
        CONFIG_FILE = fallback_file
        CONFIG_ERROR = ""
        return True
    except Exception as e:
        CONFIG_ERROR = str(e)
        return False

def build_s3(cfg):
    try:
        aws = cfg.get("aws") or {}
        if not aws.get("access_key") or not aws.get("secret_key") or not aws.get("region"):
            return None
        return boto3.client(
            "s3",
            aws_access_key_id=aws["access_key"],
            aws_secret_access_key=aws["secret_key"],
            region_name=aws["region"]
        )
    except Exception:
        return None


config = load_config()
s3 = build_s3(config) if config.get("aws") else None


# ---------- HTTP HANDLER ----------
class UploadHandler(http.server.BaseHTTPRequestHandler):
    def format_size(self, size):
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024

    def format_date(self, dt):
        try:
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""

    # ===== Polished CSS + Light/Dark mode =====
    def css(self):
        return """
        <style>
        :root {
          --bg: #0b1020;
          --bg-card: #0f162c;
          --bg-elevated: #121a36;
          --border-subtle: rgba(148,163,184,0.2);
          --accent: #22d3ee;
          --accent-2: #38bdf8;
          --accent-strong: #0ea5e9;
          --danger: #ef4444;
          --danger-soft: rgba(239,68,68,0.15);
          --text: #e2e8f0;
          --text-muted: #94a3b8;
          --text-soft: #cbd5f5;
          --success: #22c55e;
        }
        body[data-theme="light"] {
          --bg: #f3f6fb;
          --bg-card: #ffffff;
          --bg-elevated: #ffffff;
          --border-subtle: rgba(15,23,42,0.15);
          --accent: #0284c7;
          --accent-2: #0ea5e9;
          --accent-strong: #0ea5e9;
          --danger: #dc2626;
          --danger-soft: rgba(220,38,38,0.12);
          --text: #0f172a;
          --text-muted: #64748b;
          --text-soft: #334155;
          --success: #16a34a;
        }
        body {
          margin:0;
          background:
            radial-gradient(900px 500px at 10% -20%, rgba(34,211,238,0.15), transparent),
            radial-gradient(700px 600px at 90% -10%, rgba(56,189,248,0.12), transparent),
            linear-gradient(180deg, rgba(15,23,42,0.6), rgba(15,23,42,0)) 0 0 / 100% 40% no-repeat,
            var(--bg);
          color: var(--text);
          font-family: "Space Grotesk", "IBM Plex Sans", "Segoe UI", sans-serif;
          min-height: 100vh;
        }
        .top {
          position: sticky;
          top: 0;
          z-index: 10;
          background: rgba(15,23,42,0.85);
          backdrop-filter: blur(12px);
          border-bottom: 1px solid var(--border-subtle);
          padding: 16px 26px;
          font-size: 16px;
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
        .brand {
          display:flex;
          align-items:center;
          gap:12px;
        }
        .brand-mark {
          width:32px;
          height:32px;
          border-radius:10px;
          background: linear-gradient(135deg, var(--accent), var(--accent-strong));
          display:grid;
          place-items:center;
          color:#001018;
          font-weight:700;
        }
        .chip {
          font-size: 12px;
          padding:4px 8px;
          border-radius:999px;
          border:1px solid var(--border-subtle);
          background: rgba(15,23,42,0.55);
        }
        body[data-theme="light"] .chip {
          background: #eef2ff;
        }
        .top button, .top a {
          border-radius: 999px;
          border: 1px solid var(--border-subtle);
          padding: 7px 12px;
          background: rgba(15,23,42,0.2);
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
          max-width: 1200px;
          margin: 26px auto;
          padding: 0 12px 40px;
          display: flex;
          justify-content: center;
        }
        .card {
          background: var(--bg-card);
          border-radius: 18px;
          border: 1px solid var(--border-subtle);
          padding: 24px 24px 26px;
          box-shadow: 0 30px 60px rgba(2,6,23,0.25);
          animation: floatUp .35s ease both;
          width: 100%;
          max-width: 1100px;
        }
        h2 {
          margin-top:0;
          font-size:22px;
          letter-spacing: -0.01em;
        }
        .subtitle {
          font-size: 13px;
          color: var(--text-muted);
          margin-bottom: 18px;
        }
        .pill-row {
          display:flex;
          flex-wrap:wrap;
          gap:10px;
          margin: 4px 0 16px;
        }
        .pill {
          display:inline-flex;
          align-items:center;
          gap:8px;
          border-radius:999px;
          padding:6px 12px;
          border:1px solid var(--border-subtle);
          background: rgba(15,23,42,0.35);
          font-size:12px;
          color: var(--text-soft);
        }
        body[data-theme="light"] .pill {
          background: #f8fafc;
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
          border-color: var(--accent-2);
          box-shadow: 0 0 0 2px rgba(34,211,238,0.25);
        }
        .btn {
          padding: 8px 14px;
          border-radius: 10px;
          border:0;
          background: linear-gradient(135deg, var(--accent), var(--accent-strong));
          color:#001018;
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
        .btn.ghost {
          background: transparent;
          border:1px solid var(--border-subtle);
          color: var(--text);
        }
        table {
          width:100%;
          border-collapse: collapse;
          margin-top: 14px;
        }
        th, td {
          padding: 12px 6px;
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
        td.meta {
          color: var(--text-muted);
          white-space: nowrap;
        }
        td.actions {
          text-align:right;
          white-space: nowrap;
        }
        .link {
          font-size: 13px;
          color: var(--accent-2);
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
          background: linear-gradient(135deg,#fbbf24,#f97316);
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
          background: rgba(15,23,42,0.55);
          margin-top: 18px;
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
        .breadcrumbs {
          display:flex;
          flex-wrap:wrap;
          gap:8px;
          font-size: 12px;
          margin: 6px 0 14px;
        }
        .crumb {
          padding:4px 8px;
          border-radius:999px;
          border:1px solid var(--border-subtle);
          color: var(--text-soft);
          text-decoration:none;
          background: rgba(15,23,42,0.35);
        }
        .crumb.current {
          color: var(--text);
          border-color: rgba(56,189,248,0.5);
        }
        .toolbar {
          display:flex;
          justify-content:space-between;
          align-items:center;
          flex-wrap:wrap;
          gap:12px;
          margin-top: 8px;
        }
        .toolbar .left, .toolbar .right {
          display:flex;
          align-items:center;
          gap:10px;
          flex-wrap:wrap;
        }
        select.input {
          background: transparent;
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
        .status-dot {
          width:8px;
          height:8px;
          border-radius:999px;
          background: var(--success);
          display:inline-block;
        }
        .action-link {
          font-size: 12px;
          color: var(--text-soft);
          text-decoration:none;
          border:1px solid var(--border-subtle);
          padding:4px 8px;
          border-radius:999px;
          margin-left:6px;
        }
        .table-scroll {
          overflow-x: auto;
        }
        @keyframes floatUp {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (max-width: 820px) {
          .top {
            flex-direction: column;
            align-items:flex-start;
            gap: 12px;
          }
          .top .right-actions {
            flex-wrap: wrap;
          }
          .card {
            padding: 18px;
          }
          th:nth-child(3), td:nth-child(3),
          th:nth-child(4), td:nth-child(4) {
            display:none;
          }
        }
        </style>
        """

    def render_bucket_form(self, error=""):
        error_html = f"<div class='subtitle' style='color: var(--danger);'>{error}</div>" if error else ""
        return f"""
        <html><head>{self.css()}{self.scripts()}</head>
        <body data-theme="dark">
          <div class='wrap'>
            <div class='card' style='max-width:480px;margin-top:40px'>
              <h2>Connect a Bucket</h2>
              <div class='subtitle'>Enter the S3 bucket name to manage files.</div>
              {error_html}
              <form method='post' action='/save-bucket'>
                <input class='input' name='bucket' placeholder='bucket-name'><br><br>
                <button class='btn'>Continue</button>
              </form>
            </div>
          </div>
        </body></html>
        """

    def render_creds_form(self, error=""):
        error_html = f"<div class='subtitle' style='color: var(--danger);'>{error}</div>" if error else ""
        return f"""
        <html><head>{self.css()}{self.scripts()}</head>
        <body data-theme="dark">
          <div class='wrap'>
            <div class='card' style='max-width:480px;margin-top:40px'>
              <h2>AWS Credentials</h2>
              <div class='subtitle'>Access key is stored locally on this server only.</div>
              {error_html}
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

    # ===== JavaScript: theme toggling, search, and upload progress =====
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
        function initSort() {
          var select = document.getElementById('sortSelect');
          if (!select) return;
          select.addEventListener('change', function() {
            var mode = select.value;
            var tbody = document.querySelector('#fileTable tbody');
            if (!tbody) return;
            var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr[data-kind]'));
            rows.sort(function(a, b) {
              if (mode === 'name') {
                return (a.dataset.name || '').localeCompare(b.dataset.name || '');
              }
              if (mode === 'size') {
                return (parseInt(b.dataset.size || '0', 10) - parseInt(a.dataset.size || '0', 10));
              }
              if (mode === 'modified') {
                return (a.dataset.date || '').localeCompare(b.dataset.date || '');
              }
              return 0;
            });
            rows.forEach(function(r) { tbody.appendChild(r); });
          });
        }
        function initCopyButtons() {
          var buttons = document.querySelectorAll('[data-copy]');
          buttons.forEach(function(btn) {
            btn.addEventListener('click', function(e) {
              e.preventDefault();
              var val = btn.getAttribute('data-copy');
              if (!val) return;
              if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(val);
                btn.textContent = 'Copied';
                setTimeout(function(){ btn.textContent = 'Copy URI'; }, 1200);
              } else {
                window.prompt('Copy URI', val);
              }
            });
          });
        }
        function initDropzone() {
          var zone = document.getElementById('dropzone');
          var fileInput = document.getElementById('fileInput');
          if (!zone || !fileInput) return;
          ['dragenter','dragover'].forEach(function(evt) {
            zone.addEventListener(evt, function(e) {
              e.preventDefault();
              zone.classList.add('active');
            });
          });
          ['dragleave','drop'].forEach(function(evt) {
            zone.addEventListener(evt, function(e) {
              e.preventDefault();
              zone.classList.remove('active');
            });
          });
          zone.addEventListener('drop', function(e) {
            if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
              fileInput.files = e.dataTransfer.files;
            }
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
          initSort();
          initCopyButtons();
          initDropzone();
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

        # No bucket has been configured yet
        if not config.get("bucket"):
            return self.respond(self.render_bucket_form())

        # AWS credentials are not configured yet
        if not config.get("aws") or not s3:
            return self.respond(self.render_creds_form())

        p = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(p.query)
        prefix = q.get("prefix", [""])[0]
        parts = [p for p in prefix.strip("/").split("/") if p] if prefix else []
        crumbs = [("Root", "")]
        current = ""
        for part in parts:
            current += part + "/"
            crumbs.append((part, current))

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

        # ===== List objects with folder-style prefixes =====
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
        folder_count = len(folders)
        file_count = len(files)
        total_size = sum([o.get("Size", 0) for o in files])

        folder_rows = ""
        for pref in folders:
            name = pref[len(prefix):].strip("/")
            folder_rows += f"""
            <tr data-kind="folder" data-name="{name}" data-size="0" data-date="">
              <td>
                <span class='tag-folder'>
                  <span class='folder-icon'></span>
                  <span>{name}</span>
                </span>
              </td>
              <td class='meta'>Folder</td>
              <td class='size'>--</td>
              <td class='meta'>--</td>
              <td class='actions'>
                <a class='link' href='/?prefix={urllib.parse.quote(pref)}'>Open</a>
                <a class='link danger' href='/delete?file={urllib.parse.quote(pref)}'>Delete</a>
                <a class='action-link' href='#' data-copy='s3://{config["bucket"]}/{pref}'>Copy URI</a>
              </td>
            </tr>
            """

        file_rows = ""
        for o in files:
            name = o["Key"][len(prefix):] if prefix and o["Key"].startswith(prefix) else o["Key"]
            ext = os.path.splitext(name)[1].replace(".", "").upper() or "FILE"
            modified = o.get("LastModified", "")
            modified_iso = modified.isoformat() if hasattr(modified, "isoformat") else ""
            file_rows += f"""
            <tr data-kind="file" data-name="{name}" data-size="{o.get('Size', 0)}" data-date="{modified_iso}">
              <td><span class='file-icon'></span>{name}</td>
              <td class='meta'>{ext}</td>
              <td class='size'>{self.format_size(o.get("Size", 0))}</td>
              <td class='meta'>{self.format_date(modified)}</td>
              <td class='actions'>
                <a class='link' href='/download?file={urllib.parse.quote(o["Key"])}'>Download</a>
                <a class='link danger' href='/delete?file={urllib.parse.quote(o["Key"])}'>Delete</a>
                <a class='action-link' href='#' data-copy='s3://{config["bucket"]}/{o["Key"]}'>Copy URI</a>
              </td>
            </tr>
            """

        rows = folder_rows + file_rows
        if not rows:
            rows = "<tr><td colspan='5' class='empty'>No files in this folder</td></tr>"

        prefix_label = "/" if not prefix else "/" + prefix.strip("/")
        crumbs_html = ""
        for i, (name, path) in enumerate(crumbs):
            cls = "crumb current" if i == len(crumbs) - 1 else "crumb"
            target = f"/?prefix={urllib.parse.quote(path)}" if path else "/"
            crumbs_html += f"<a class='{cls}' href='{target}'>{name}</a>"
        stats_html = f"""
        <div class='pill-row'>
          <span class='pill'><span class='status-dot'></span>{file_count} files</span>
          <span class='pill'>{folder_count} folders</span>
          <span class='pill'>Total size {self.format_size(total_size)}</span>
        </div>
        """

        html = f"""
        <html><head>{self.css()}{self.scripts()}</head>
        <body data-theme="dark">
          <div class='top'>
            <div class='brand'>
              <div class='brand-mark'>S3</div>
              <div>
                S3 File Manager
                <span class='chip'>{config['bucket']}</span>
              </div>
            </div>
            <div class='right-actions'>
              <span class='badge-prefix'>{prefix_label}</span>
              <span class='chip'><span class='status-dot'></span>Connected</span>
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

              <div class='breadcrumbs'>
                {crumbs_html}
              </div>

              {stats_html}

              <div class='toolbar'>
                <div class='left'>
                  <input id='searchBox' class='input' placeholder='Search files or folders...'>
                  <select id='sortSelect' class='input' style='max-width:180px'>
                    <option value='name'>Sort: Name</option>
                    <option value='size'>Sort: Size</option>
                    <option value='modified'>Sort: Modified</option>
                  </select>
                </div>
                <div class='right'>
                  <a class='action-link' href='/?prefix={urllib.parse.quote(prefix)}'>Refresh</a>
                  <a class='action-link' href='#' data-copy='s3://{config["bucket"]}/{prefix}'>Copy Prefix</a>
                </div>
              </div>

              <div class='table-scroll'>
                <table id='fileTable'>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Size</th>
                      <th>Modified</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows}
                  </tbody>
                </table>
              </div>

              <div class='uploadbox'>
                <form id='uploadForm' method='post' enctype='multipart/form-data'>
                  <input type='hidden' name='prefix' value='{prefix}'>
                  <div id='dropzone' class='dropzone'>
                    <div>
                      <div style='font-weight:600'>Drag & drop files</div>
                      <div class='muted' style='font-size:12px'>or pick a file to upload</div>
                    </div>
                    <div>
                      <input id='fileInput' type='file' name='file'>
                    </div>
                  </div>
                  <div class='upload-row'>
                    <div class='muted'>Uploads stay in the current folder.</div>
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
            if not bucket:
                return self.respond(self.render_bucket_form("Bucket name is required."))
            config["bucket"] = bucket
            if not save_config(config):
                return self.respond(self.render_bucket_form("Unable to save configuration. Check permissions."))
            return self.respond("<script>location='/'</script>")

        if self.path == "/save-creds":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            access_key = form.get("access_key", [""])[0].strip()
            secret_key = form.get("secret_key", [""])[0].strip()
            region = form.get("region", ["us-east-1"])[0].strip()
            if not access_key or not secret_key or not region:
                return self.respond(self.render_creds_form("All fields are required."))
            config["aws"] = {
                "access_key": access_key,
                "secret_key": secret_key,
                "region": region,
            }
            if not save_config(config):
                return self.respond(self.render_creds_form("Unable to save configuration. Check permissions."))
            global s3
            s3 = build_s3(config)
            if not s3:
                config.pop("aws", None)
                save_config(config)
                return self.respond(self.render_creds_form("Credentials are invalid or incomplete."))
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

        # Handle upload (including prefix when provided)
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
class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

try:
    with ReusableTCPServer(("", PORT), UploadHandler) as httpd:
        print(f"Serving S3 manager on port {PORT} (HTTP)")
        httpd.serve_forever()
except OSError as e:
    print(f"Server failed to start on port {PORT}: {e}")
    sys.exit(1)

