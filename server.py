#!/usr/bin/env python3

import http.server, socketserver, urllib.parse, cgi
import base64
import html
import mimetypes
import time
import os
import sys
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
AUTH_USER = os.getenv("S3MGR_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("S3MGR_PASSWORD", "")


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
          --bg: #0b1117;
          --bg-card: rgba(14, 20, 33, 0.92);
          --bg-elevated: rgba(18, 26, 44, 0.9);
          --border-subtle: rgba(148,163,184,0.2);
          --accent: #2dd4bf;
          --accent-2: #38bdf8;
          --accent-strong: #0ea5e9;
          --danger: #f97316;
          --danger-soft: rgba(249,115,22,0.2);
          --text: #e2e8f0;
          --text-muted: #94a3b8;
          --text-soft: #cbd5f5;
          --success: #22c55e;
          --shadow: 0 30px 70px rgba(2, 6, 23, 0.45);
          --glow: 0 0 40px rgba(45, 212, 191, 0.2);
        }
        body[data-theme="light"] {
          --bg: #f6f3ef;
          --bg-card: rgba(255, 255, 255, 0.98);
          --bg-elevated: #ffffff;
          --border-subtle: rgba(15,23,42,0.12);
          --accent: #0ea5e9;
          --accent-2: #14b8a6;
          --accent-strong: #0284c7;
          --danger: #ea580c;
          --danger-soft: rgba(234,88,12,0.12);
          --text: #0f172a;
          --text-muted: #64748b;
          --text-soft: #334155;
          --success: #16a34a;
          --shadow: 0 20px 50px rgba(15, 23, 42, 0.18);
          --glow: 0 0 40px rgba(14, 165, 233, 0.15);
        }
        body {
          margin:0;
          background:
            radial-gradient(800px 500px at 12% -20%, rgba(45,212,191,0.2), transparent),
            radial-gradient(700px 600px at 88% -10%, rgba(14,165,233,0.18), transparent),
            linear-gradient(180deg, rgba(15,23,42,0.7), rgba(15,23,42,0)) 0 0 / 100% 45% no-repeat,
            var(--bg);
          color: var(--text);
          font-family: "Bricolage Grotesque", "Space Grotesk", "IBM Plex Sans", sans-serif;
          min-height: 100vh;
        }
        .bg-orb {
          position: fixed;
          width: 420px;
          height: 420px;
          border-radius: 50%;
          filter: blur(60px);
          opacity: 0.6;
          z-index: 0;
          pointer-events: none;
        }
        .orb-1 {
          top: -160px;
          left: -100px;
          background: radial-gradient(circle, rgba(45,212,191,0.5), transparent 70%);
        }
        .orb-2 {
          right: -120px;
          top: 40px;
          background: radial-gradient(circle, rgba(14,165,233,0.5), transparent 70%);
        }
        .orb-3 {
          bottom: -180px;
          left: 15%;
          background: radial-gradient(circle, rgba(249,115,22,0.4), transparent 70%);
        }
        .page {
          position: relative;
          z-index: 1;
        }
        .top {
          position: sticky;
          top: 0;
          z-index: 10;
          background: rgba(10,15,25,0.7);
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
          background: rgba(15,23,42,0.45);
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
          box-shadow: var(--shadow);
          animation: floatUp .35s ease both;
          width: 100%;
          max-width: 1100px;
        }
        .section-title {
          margin: 18px 0 10px;
          font-size: 13px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--text-muted);
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
        .stat-grid {
          display:grid;
          grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
          gap:12px;
          margin: 12px 0 18px;
        }
        .stat-card {
          padding: 14px 16px;
          border-radius: 16px;
          background: var(--bg-elevated);
          border: 1px solid var(--border-subtle);
          box-shadow: var(--glow);
        }
        .stat-card .label {
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: var(--text-muted);
        }
        .stat-card .value {
          font-size: 18px;
          font-weight: 600;
          margin-top: 6px;
        }
        .stat-card .meta {
          font-size: 12px;
          color: var(--text-muted);
          margin-top: 4px;
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
        .input::placeholder {
          color: var(--text-muted);
        }
        .input:focus {
          outline:none;
          border-color: var(--accent-2);
          box-shadow: 0 0 0 2px rgba(34,211,238,0.25);
        }
        .input:focus-visible,
        .btn:focus-visible,
        a:focus-visible {
          outline: 2px solid rgba(34,211,238,0.5);
          outline-offset: 2px;
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
        .btn.ghost.active {
          border-color: var(--accent-2);
          box-shadow: 0 0 0 2px rgba(56,189,248,0.15);
          color: var(--text);
        }
        .btn.warn {
          background: linear-gradient(135deg, #fb923c, #f97316);
          color: #1f1306;
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
        tbody tr:hover {
          background: rgba(14,165,233,0.08);
        }
        th {
          color: var(--text-soft);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          font-size: 11px;
        }
        th.col-select, td.col-select {
          width: 28px;
          text-align: center;
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
        .file-icon {
          width: 18px;
          height: 18px;
          border-radius: 6px;
          background: linear-gradient(135deg, rgba(14,165,233,0.9), rgba(45,212,191,0.9));
          display: inline-block;
          margin-right: 8px;
          vertical-align: middle;
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
        .toolbar-group {
          display:flex;
          align-items:center;
          gap:10px;
          flex-wrap:wrap;
        }
        .toolbar form {
          display:flex;
          align-items:center;
          gap:8px;
          flex-wrap:wrap;
        }
        .toolbar .left, .toolbar .right {
          display:flex;
          align-items:center;
          gap:10px;
          flex-wrap:wrap;
        }
        select.input {
          background: var(--bg-elevated);
          color: var(--text);
        }
        select.input option {
          background: var(--bg-elevated);
          color: var(--text);
        }
        body[data-theme="light"] select.input option {
          background: #ffffff;
          color: #0f172a;
        }
        .view-toggle {
          display:flex;
          gap:6px;
        }
        .auth-form {
          display:flex;
          flex-direction:column;
          gap:12px;
        }
        .auth-form .btn {
          align-self:center;
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
        .checkbox {
          width: 16px;
          height: 16px;
          accent-color: var(--accent-2);
        }
        .bulk-bar {
          display:flex;
          flex-wrap:wrap;
          gap:10px;
          align-items:center;
          margin-top: 12px;
          padding: 10px 12px;
          border-radius: 12px;
          border: 1px solid var(--border-subtle);
          background: rgba(15,23,42,0.35);
        }
        .bulk-bar.hidden {
          display:none;
        }
        body[data-theme="light"] .bulk-bar {
          background: #f8fafc;
        }
        .bulk-input {
          max-width: 220px;
        }
        .mono {
          font-family: "Space Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        }
        .pager {
          display:flex;
          justify-content:flex-end;
          gap:8px;
          margin-top: 14px;
        }
        .preview-wrap {
          max-width: 900px;
          margin: 40px auto;
          padding: 0 16px 40px;
        }
        .preview-card {
          background: var(--bg-card);
          border-radius: 18px;
          border: 1px solid var(--border-subtle);
          padding: 20px;
          box-shadow: var(--shadow);
        }
        .preview-header {
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:12px;
          margin-bottom: 16px;
        }
        .preview-frame {
          width:100%;
          border-radius: 14px;
          border: 1px solid var(--border-subtle);
          background: rgba(15,23,42,0.2);
          padding: 12px;
          word-break: break-all;
          overflow-wrap: anywhere;
        }
        .share-box {
          background: linear-gradient(135deg, rgba(14,165,233,0.12), rgba(45,212,191,0.12));
          border: 1px solid rgba(56,189,248,0.35);
          color: var(--text);
          font-size: 12px;
          line-height: 1.5;
          min-height: 88px;
          display: flex;
          align-items: center;
          white-space: normal;
          overflow-wrap: anywhere;
          word-break: break-word;
          overflow: auto;
        }
        .dropzone {
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:16px;
          padding: 12px 14px;
          border-radius: 12px;
          border: 1px dashed var(--border-subtle);
          background: rgba(15,23,42,0.3);
          transition: border-color .2s ease, background .2s ease, transform .2s ease;
        }
        body[data-theme="light"] .dropzone {
          background: #f8fafc;
        }
        .dropzone.active {
          border-color: var(--accent-2);
          background: rgba(45,212,191,0.08);
          transform: translateY(-1px);
        }
        .dropzone input[type="file"] {
          color: var(--text);
        }
        .grid {
          display:none;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap:16px;
          margin-top: 18px;
        }
        .grid-item {
          border-radius: 16px;
          padding: 14px 16px;
          border: 1px solid var(--border-subtle);
          background: var(--bg-elevated);
          box-shadow: 0 12px 24px rgba(2,6,23,0.2);
          display:flex;
          flex-direction:column;
          gap:10px;
        }
        .grid-head {
          display:flex;
          align-items:center;
          gap:10px;
        }
        .grid-title {
          font-weight:600;
          font-size:14px;
          word-break: break-word;
        }
        .grid-meta {
          display:flex;
          flex-wrap:wrap;
          gap:8px;
          font-size:12px;
          color: var(--text-muted);
        }
        .meta-pill {
          padding: 4px 8px;
          border-radius: 999px;
          border: 1px solid var(--border-subtle);
          color: var(--text-soft);
          font-size: 11px;
        }
        .grid-actions {
          margin-top: auto;
          display:flex;
          flex-wrap:wrap;
          gap:6px;
        }
        .toast {
          position: fixed;
          bottom: 22px;
          right: 22px;
          background: rgba(15,23,42,0.9);
          color: var(--text);
          padding: 10px 14px;
          border-radius: 12px;
          border: 1px solid var(--border-subtle);
          font-size: 12px;
          box-shadow: var(--shadow);
          opacity: 0;
          transform: translateY(8px);
          transition: opacity .2s ease, transform .2s ease;
          pointer-events: none;
          z-index: 20;
        }
        .toast.show {
          opacity: 1;
          transform: translateY(0);
        }
        .modal-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(2, 6, 23, 0.6);
          display: none;
          align-items: center;
          justify-content: center;
          z-index: 30;
          padding: 16px;
        }
        .modal {
          width: 100%;
          max-width: 420px;
          border-radius: 16px;
          border: 1px solid var(--border-subtle);
          background: var(--bg-card);
          box-shadow: var(--shadow);
          padding: 18px;
        }
        .modal h3 {
          margin: 0 0 8px;
          font-size: 16px;
        }
        .modal p {
          margin: 0 0 14px;
          color: var(--text-muted);
          font-size: 13px;
        }
        .modal-actions {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
        }
        .modal-backdrop.show {
          display: flex;
        }
        .modal input {
          width: 100%;
          margin: 8px 0 12px;
          padding: 10px 11px;
          border-radius: 10px;
          border: 1px solid var(--border-subtle);
          background: transparent;
          color: var(--text);
          font-size: 14px;
        }
        .is-hidden {
          display:none !important;
        }
        body[data-view="grid"] .table-scroll {
          display:none;
        }
        body[data-view="grid"] .grid {
          display:grid;
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
          th:nth-child(4), td:nth-child(4),
          th:nth-child(5), td:nth-child(5) {
            display:none;
          }
          .grid {
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          }
        }
        </style>
        """

    def fonts(self):
        return """
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
        """

    def render_bucket_form(self, error=""):
        error_html = f"<div class='subtitle' style='color: var(--danger);'>{error}</div>" if error else ""
        return f"""
        <html><head>{self.fonts()}{self.css()}{self.scripts()}</head>
        <body data-theme="dark">
          <div class='bg-orb orb-1'></div>
          <div class='bg-orb orb-2'></div>
          <div class='bg-orb orb-3'></div>
          <div class='page'>
          <div class='wrap'>
            <div class='card' style='max-width:480px;margin-top:40px'>
              <h2>Connect a Bucket</h2>
              <div class='subtitle'>Enter the S3 bucket name to manage files.</div>
              {error_html}
              <form class='auth-form' method='post' action='/save-bucket'>
                <input class='input' name='bucket' placeholder='bucket-name'>
                <button class='btn'>Continue</button>
              </form>
            </div>
          </div>
          </div>
        </body></html>
        """

    def render_creds_form(self, error=""):
        error_html = f"<div class='subtitle' style='color: var(--danger);'>{error}</div>" if error else ""
        return f"""
        <html><head>{self.fonts()}{self.css()}{self.scripts()}</head>
        <body data-theme="dark">
          <div class='bg-orb orb-1'></div>
          <div class='bg-orb orb-2'></div>
          <div class='bg-orb orb-3'></div>
          <div class='page'>
          <div class='wrap'>
            <div class='card' style='max-width:480px;margin-top:40px'>
              <h2>AWS Credentials</h2>
              <div class='subtitle'>Access key is stored locally on this server only.</div>
              {error_html}
              <form class='auth-form' method='post' action='/save-creds'>
                <input class='input' name='access_key' placeholder='Access Key'>
                <input class='input' name='secret_key' placeholder='Secret Key'>
                <input class='input' name='region' value='us-east-1'>
                <button class='btn'>Save</button>
              </form>
            </div>
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
        function applyView() {
          var saved = localStorage.getItem('s3mgr-view') || 'table';
          document.body.setAttribute('data-view', saved);
          var tableBtn = document.getElementById('viewTable');
          var gridBtn = document.getElementById('viewGrid');
          if (tableBtn && gridBtn) {
            tableBtn.classList.toggle('active', saved === 'table');
            gridBtn.classList.toggle('active', saved === 'grid');
          }
        }
        function toggleTheme() {
          var cur = document.body.getAttribute('data-theme') || 'dark';
          var next = cur === 'dark' ? 'light' : 'dark';
          document.body.setAttribute('data-theme', next);
          localStorage.setItem('s3mgr-theme', next);
        }
        function toggleView(view) {
          document.body.setAttribute('data-view', view);
          localStorage.setItem('s3mgr-view', view);
          applyView();
        }
        function applyFilters() {
          var box = document.getElementById('searchBox');
          var filter = document.getElementById('typeFilter');
          var q = box ? box.value.toLowerCase() : '';
          var kind = filter ? filter.value : 'all';
          var rows = document.querySelectorAll('#fileTable tbody tr[data-kind]');
          var cards = document.querySelectorAll('.grid-item[data-kind]');
          function match(el) {
            var name = (el.getAttribute('data-name') || '').toLowerCase();
            var kindMatches = kind === 'all' || el.getAttribute('data-kind') === kind;
            var textMatches = !q || name.indexOf(q) !== -1;
            el.classList.toggle('is-hidden', !(kindMatches && textMatches));
          }
          rows.forEach(match);
          cards.forEach(match);
        }
        function initSearch() {
          var box = document.getElementById('searchBox');
          var filter = document.getElementById('typeFilter');
          if (!box) return;
          box.addEventListener('input', applyFilters);
          if (filter) {
            filter.addEventListener('change', applyFilters);
          }
        }
        function initSort() {
          var select = document.getElementById('sortSelect');
          if (!select) return;
          select.addEventListener('change', function() {
            var mode = select.value;
            var tbody = document.querySelector('#fileTable tbody');
            var grid = document.getElementById('gridItems');
            if (!tbody) return;
            var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr[data-kind]'));
            var cards = Array.prototype.slice.call(document.querySelectorAll('.grid-item[data-kind]'));
            rows.sort(function(a, b) {
              if (mode === 'name') {
                return (a.dataset.name || '').localeCompare(b.dataset.name || '');
              }
              if (mode === 'size') {
                return (parseInt(b.dataset.size || '0', 10) - parseInt(a.dataset.size || '0', 10));
              }
              if (mode === 'modified') {
                return (b.dataset.date || '').localeCompare(a.dataset.date || '');
              }
              return 0;
            });
            rows.forEach(function(r) { tbody.appendChild(r); });
            if (grid) {
              cards.sort(function(a, b) {
                if (mode === 'name') {
                  return (a.dataset.name || '').localeCompare(b.dataset.name || '');
                }
                if (mode === 'size') {
                  return (parseInt(b.dataset.size || '0', 10) - parseInt(a.dataset.size || '0', 10));
                }
                if (mode === 'modified') {
                  return (b.dataset.date || '').localeCompare(a.dataset.date || '');
                }
                return 0;
              });
              cards.forEach(function(c) { grid.appendChild(c); });
            }
          });
        }
        function showToast(message) {
          var toast = document.getElementById('toast');
          if (!toast) return;
          toast.textContent = message;
          toast.classList.add('show');
          setTimeout(function() { toast.classList.remove('show'); }, 1400);
        }
        function openModal(opts) {
          var modal = document.getElementById('confirmModal');
          if (!modal) return;
          var titleEl = document.getElementById('confirmTitle');
          var msgEl = document.getElementById('confirmMessage');
          var okBtn = document.getElementById('confirmOk');
          var cancelBtn = document.getElementById('confirmCancel');
          var input = document.getElementById('confirmInput');
          if (titleEl) titleEl.textContent = opts.title || 'Confirm';
          if (msgEl) msgEl.textContent = opts.message || '';
          if (okBtn) okBtn.textContent = opts.okText || 'OK';
          if (cancelBtn) cancelBtn.textContent = opts.cancelText || 'Cancel';
          if (input) {
            input.value = opts.inputValue || '';
            input.placeholder = opts.inputPlaceholder || '';
            input.classList.toggle('is-hidden', !opts.showInput);
            input.readOnly = !!opts.readOnly;
          }
          function close() {
            modal.classList.remove('show');
            okBtn.removeEventListener('click', okHandler);
            cancelBtn.removeEventListener('click', close);
            modal.removeEventListener('click', backdropClose);
          }
          function okHandler() {
            var value = input ? input.value : '';
            close();
            if (opts.onConfirm) opts.onConfirm(value);
          }
          function backdropClose(e) {
            if (e.target === modal) close();
          }
          okBtn.addEventListener('click', okHandler);
          cancelBtn.addEventListener('click', close);
          modal.addEventListener('click', backdropClose);
          modal.classList.add('show');
          if (input && opts.showInput) {
            setTimeout(function() { input.focus(); input.select(); }, 50);
          }
        }
        function showConfirm(title, message, onConfirm) {
          openModal({ title: title, message: message, okText: 'Delete', onConfirm: onConfirm });
        }
        function showAlert(title, message) {
          openModal({ title: title, message: message, okText: 'OK', cancelText: 'Close' });
        }
        function showPrompt(title, message, defaultValue, onConfirm) {
          openModal({
            title: title,
            message: message,
            okText: 'Save',
            showInput: true,
            inputValue: defaultValue || '',
            onConfirm: onConfirm
          });
        }
        function showCopyFallback(text) {
          openModal({
            title: 'Copy URL',
            message: 'Copy the link below:',
            okText: 'Done',
            cancelText: 'Close',
            showInput: true,
            inputValue: text || '',
            readOnly: true
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
                showToast('Copied to clipboard');
              } else {
                showCopyFallback(val);
              }
            });
          });
        }
        function initDropzone() {
          var zone = document.getElementById('dropzone');
          var fileInput = document.getElementById('fileInput');
          var fileLabel = document.getElementById('fileCount');
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
              if (fileLabel) {
                fileLabel.textContent = e.dataTransfer.files.length + ' files selected';
              }
            }
          });
        }
        function initUpload() {
          var form = document.getElementById('uploadForm');
          if (!form) return;
          var bar = document.getElementById('progressFill');
          var wrap = document.getElementById('progressWrap');
          var txt = document.getElementById('progressText');
          var fileLabel = document.getElementById('fileCount');
          form.addEventListener('submit', function(e) {
            e.preventDefault();
            var fileInput = document.getElementById('fileInput');
            if (!fileInput || !fileInput.files.length) {
              showAlert('Upload', 'Choose a file first');
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
                txt.textContent = (xhr.responseText && xhr.responseText.trim()) ? xhr.responseText : ('Error ' + xhr.status);
              }
            };
            xhr.onerror = function() {
              txt.textContent = 'Upload failed';
            };

            var fd = new FormData(form);
            xhr.send(fd);
          });
          var fileInput = document.getElementById('fileInput');
          if (fileInput && fileLabel) {
            fileInput.addEventListener('change', function() {
              var count = fileInput.files ? fileInput.files.length : 0;
              fileLabel.textContent = count ? (count + ' files selected') : 'No files selected';
            });
          }
        }
        function getSelectedKeys() {
          var boxes = document.querySelectorAll('.row-select:checked');
          var keys = [];
          boxes.forEach(function(box) {
            var key = box.getAttribute('data-key');
            if (key && keys.indexOf(key) === -1) {
              keys.push(key);
            }
          });
          return keys;
        }
        function syncCheckboxes(key, checked) {
          var boxes = document.querySelectorAll('.row-select');
          boxes.forEach(function(box) {
            if (box.getAttribute('data-key') === key) {
              box.checked = checked;
            }
          });
        }
        function updateSelectionCount() {
          var label = document.getElementById('selectedCount');
          var bar = document.getElementById('bulkBar');
          if (!label) return;
          var keys = getSelectedKeys();
          label.textContent = keys.length + ' selected';
          if (bar) {
            bar.classList.toggle('hidden', keys.length === 0);
          }
        }
        function initSelection() {
          var boxes = document.querySelectorAll('.row-select');
          boxes.forEach(function(box) {
            box.addEventListener('change', function() {
              var key = box.getAttribute('data-key');
              syncCheckboxes(key, box.checked);
              updateSelectionCount();
            });
          });
          var selectAll = document.getElementById('selectAll');
          if (selectAll) {
            selectAll.addEventListener('change', function() {
              var rows = document.querySelectorAll('.row-select');
              rows.forEach(function(box) {
                var container = box.closest('.is-hidden');
                if (!container) {
                  box.checked = selectAll.checked;
                }
              });
              updateSelectionCount();
            });
          }
          updateSelectionCount();
        }
        function submitBulk(action) {
          var keys = getSelectedKeys();
          if (!keys.length) {
            showAlert('Bulk action', 'Select files or folders first');
            return;
          }
          if (action === 'delete') {
            showConfirm('Delete selected', 'Delete all selected items? This cannot be undone.', function() {
              proceedBulk(action, keys, form, target, targetHidden);
            });
            return;
          }
          var form = document.getElementById('bulkForm');
          var target = document.getElementById('bulkTarget');
          var targetHidden = document.getElementById('bulkTargetHidden');
          if (!form) return;
          proceedBulk(action, keys, form, target, targetHidden);
        }
        function proceedBulk(action, keys, form, target, targetHidden) {
          if (!form) return;
          form.querySelectorAll('input[name="keys"]').forEach(function(el) { el.remove(); });
          keys.forEach(function(k) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'keys';
            input.value = k;
            form.appendChild(input);
          });
          var actionInput = document.getElementById('bulkAction');
          if (actionInput) actionInput.value = action;
          if ((action === 'move' || action === 'copy') && (!target || !target.value)) {
            showAlert('Bulk action', 'Enter a target prefix');
            return;
          }
          if (targetHidden) {
            targetHidden.value = target && target.value ? target.value : '';
          }
          form.submit();
        }
        function initBulkActions() {
          var deleteBtn = document.getElementById('bulkDelete');
          var moveBtn = document.getElementById('bulkMove');
          var copyBtn = document.getElementById('bulkCopy');
          if (deleteBtn) {
            deleteBtn.addEventListener('click', function(e) {
              e.preventDefault();
              showConfirm('Delete selected', 'Delete all selected items? This cannot be undone.', function() {
                submitBulk('delete');
              });
            });
          }
          if (moveBtn) moveBtn.addEventListener('click', function(e) { e.preventDefault(); submitBulk('move'); });
          if (copyBtn) copyBtn.addEventListener('click', function(e) { e.preventDefault(); submitBulk('copy'); });
        }
        function initDeleteLinks() {
          var links = document.querySelectorAll('[data-delete-url]');
          links.forEach(function(link) {
            link.addEventListener('click', function(e) {
              e.preventDefault();
              var url = link.getAttribute('data-delete-url');
              if (!url) return;
              showConfirm('Delete item', 'Delete this item? This cannot be undone.', function() {
                window.location.href = url;
              });
            });
          });
        }
        function initRename() {
          var renames = document.querySelectorAll('[data-rename]');
          renames.forEach(function(btn) {
            btn.addEventListener('click', function(e) {
              e.preventDefault();
              var key = btn.getAttribute('data-rename');
              var current = btn.getAttribute('data-name') || key;
              showPrompt('Rename item', 'Enter the new name', current, function(next) {
                if (!next || next === current) return;
                var form = document.getElementById('renameForm');
                if (!form) return;
                form.querySelector('input[name="old"]').value = key;
                form.querySelector('input[name="new"]').value = next;
                form.submit();
              });
            });
          });
        }
        document.addEventListener('DOMContentLoaded', function() {
          applyTheme();
          applyView();
          var themeBtn = document.getElementById('themeToggle');
          if (themeBtn) {
            themeBtn.addEventListener('click', function(e) {
              e.preventDefault();
              toggleTheme();
            });
          }
          var tableBtn = document.getElementById('viewTable');
          var gridBtn = document.getElementById('viewGrid');
          if (tableBtn && gridBtn) {
            tableBtn.addEventListener('click', function(e) {
              e.preventDefault();
              toggleView('table');
            });
            gridBtn.addEventListener('click', function(e) {
              e.preventDefault();
              toggleView('grid');
            });
          }
          var refresh = document.getElementById('lastRefresh');
          if (refresh) {
            refresh.textContent = new Date().toLocaleTimeString();
          }
          initSearch();
          applyFilters();
          initUpload();
          initSort();
          initCopyButtons();
          initDropzone();
          initSelection();
          initBulkActions();
          initRename();
          initDeleteLinks();
        });
        </script>
        """

    def respond(self, html):
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def respond_text(self, status, text, content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def is_authenticated(self):
        if not AUTH_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            encoded = header.split(" ", 1)[1].strip()
            decoded = base64.b64decode(encoded).decode("utf-8")
            user, pwd = decoded.split(":", 1)
            return user == AUTH_USER and pwd == AUTH_PASSWORD
        except Exception:
            return False

    def send_auth_required(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="S3 File Manager"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Authentication required")

    def presign_url(self, key, expires=900):
        try:
            return s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": config["bucket"], "Key": key},
                ExpiresIn=expires
            )
        except Exception:
            return ""

    def stream_object(self, key, download=True, override_type=""):
        try:
            obj = s3.get_object(Bucket=config["bucket"], Key=key)
            content_type = override_type or obj.get("ContentType") or mimetypes.guess_type(key)[0] or "application/octet-stream"
            filename = os.path.basename(key)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            if "ContentLength" in obj:
                self.send_header("Content-Length", str(obj["ContentLength"]))
            self.end_headers()
            body = obj["Body"]
            while True:
                chunk = body.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
            return True
        except Exception:
            return False

    def copy_prefix(self, old_prefix, new_prefix, delete_source=False):
        token = ""
        while True:
            args = {
                "Bucket": config["bucket"],
                "Prefix": old_prefix
            }
            if token:
                args["ContinuationToken"] = token
            resp = s3.list_objects_v2(**args)
            for obj in resp.get("Contents", []):
                src_key = obj["Key"]
                dst_key = new_prefix + src_key[len(old_prefix):]
                s3.copy_object(
                    Bucket=config["bucket"],
                    CopySource={"Bucket": config["bucket"], "Key": src_key},
                    Key=dst_key
                )
                if delete_source:
                    s3.delete_object(Bucket=config["bucket"], Key=src_key)
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken", "")

    # ===== GET =====
    def do_GET(self):
        global config, s3
        if not self.is_authenticated():
            return self.send_auth_required()

        # No bucket has been configured yet
        if not config.get("bucket"):
            return self.respond(self.render_bucket_form())

        # AWS credentials are not configured yet
        if not config.get("aws") or not s3:
            return self.respond(self.render_creds_form())

        p = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(p.query)
        prefix = q.get("prefix", [""])[0]
        token = q.get("token", [""])[0]
        query = q.get("q", [""])[0].strip()
        max_keys_raw = q.get("max", ["500"])[0]
        try:
            max_keys = max(50, min(1000, int(max_keys_raw)))
        except Exception:
            max_keys = 500
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
                if self.stream_object(key, download=True):
                    return
                return self.respond("<html><body>Download failed</body></html>")
            except Exception:
                return self.respond("<html><body>Download failed</body></html>")

        if p.path == "/download-server":
            try:
                key = q.get("file", [""])[0]
                local = f"/tmp/{os.path.basename(key)}"
                s3.download_file(config["bucket"], key, local)
                return self.respond(f"<html><body>Downloaded to {local}</body></html>")
            except Exception:
                return self.respond("<html><body>Download failed</body></html>")

        if p.path == "/presign":
            key = q.get("file", [""])[0]
            back_prefix = q.get("prefix", [""])[0]
            back_url = f"/?prefix={urllib.parse.quote(back_prefix)}" if back_prefix else "/"
            url = self.presign_url(key, expires=900)
            if not url:
                return self.respond("<html><body>Failed to create link</body></html>")
            safe_key = html.escape(key)
            safe_url = html.escape(url)
            return self.respond(f"""
            <html><head>{self.fonts()}{self.css()}{self.scripts()}</head>
            <body data-theme="dark">
              <div class='bg-orb orb-1'></div>
              <div class='bg-orb orb-2'></div>
              <div class='bg-orb orb-3'></div>
              <div class='page'>
                <div class='preview-wrap'>
                  <div class='preview-card'>
                    <div class='preview-header'>
                      <div>
                        <div style='font-weight:600'>Share link</div>
                        <div class='muted' style='font-size:12px'>{safe_key}</div>
                      </div>
                      <div style='display:flex;gap:8px;align-items:center;'>
                        <a class='action-link' href='{back_url}'>Back</a>
                        <a class='action-link' href='{safe_url}' target='_blank'>Open</a>
                      </div>
                    </div>
                    <div class='preview-frame share-box mono'>{safe_url}</div>
                    <div style='margin-top:12px'>
                      <a class='action-link' href='#' data-copy='{safe_url}'>Copy URL</a>
                    </div>
                  </div>
                </div>
                <div id='toast' class='toast'></div>
              </div>
            </body></html>
            """)

        if p.path == "/preview":
            key = q.get("file", [""])[0]
            back_prefix = q.get("prefix", [""])[0]
            back_url = f"/?prefix={urllib.parse.quote(back_prefix)}" if back_prefix else "/"
            ext = os.path.splitext(key)[1].lower()
            mime = mimetypes.guess_type(key)[0] or ""
            url = self.presign_url(key, expires=900)
            safe_key = html.escape(key)
            if not url:
                return self.respond("<html><body>Preview failed</body></html>")
            embed = ""
            if mime.startswith("image/"):
                embed = f"<img src='{html.escape(url)}' style='max-width:100%;border-radius:12px;'>"
            elif mime.startswith("video/"):
                embed = f"<video controls style='width:100%;border-radius:12px;' src='{html.escape(url)}'></video>"
            elif mime.startswith("audio/"):
                embed = f"<audio controls style='width:100%' src='{html.escape(url)}'></audio>"
            elif ext == ".pdf":
                embed = f"<iframe src='{html.escape(url)}' style='width:100%;height:70vh;border:0;border-radius:12px;'></iframe>"
            elif mime.startswith("text/") or ext in [".log", ".md", ".json", ".txt", ".csv"]:
                try:
                    obj = s3.get_object(Bucket=config["bucket"], Key=key)
                    body = obj["Body"].read(200000).decode("utf-8", errors="replace")
                    embed = f"<pre class='preview-frame mono'>{html.escape(body)}</pre>"
                except Exception:
                    embed = "<div class='preview-frame'>Unable to load text preview.</div>"
            else:
                embed = f"<div class='preview-frame'>Preview not supported. <a class='action-link' href='{html.escape(url)}' target='_blank'>Open file</a></div>"
            return self.respond(f"""
            <html><head>{self.fonts()}{self.css()}{self.scripts()}</head>
            <body data-theme="dark">
              <div class='bg-orb orb-1'></div>
              <div class='bg-orb orb-2'></div>
              <div class='bg-orb orb-3'></div>
              <div class='page'>
                <div class='preview-wrap'>
                  <div class='preview-card'>
                    <div class='preview-header'>
                      <div>
                        <div style='font-weight:600'>Preview</div>
                        <div class='muted' style='font-size:12px'>{safe_key}</div>
                      </div>
                      <div style='display:flex;gap:8px;align-items:center;'>
                        <a class='action-link' href='{back_url}'>Back</a>
                        <a class='action-link' href='/download?file={urllib.parse.quote(key)}'>Download</a>
                      </div>
                    </div>
                    {embed}
                  </div>
                </div>
                <div id='toast' class='toast'></div>
              </div>
            </body></html>
            """)

        if p.path == "/delete":
            try:
                key = q.get("file", [""])[0]
                s3.delete_object(Bucket=config["bucket"], Key=key)
                back = f"/?prefix={urllib.parse.quote(prefix)}"
                if query:
                    back += f"&q={urllib.parse.quote(query)}"
                return self.respond(f"<script>location='{back}'</script>")
            except Exception:
                return self.respond("<html><body>Delete failed</body></html>")

        # ===== List objects with folder-style prefixes =====
        try:
            list_args = {
                "Bucket": config["bucket"],
                "Prefix": prefix if prefix else "",
                "Delimiter": "/",
                "MaxKeys": max_keys
            }
            if token:
                list_args["ContinuationToken"] = token
            resp = s3.list_objects_v2(**list_args)
        except Exception:
            resp = {}

        folders = [cp["Prefix"] for cp in resp.get("CommonPrefixes", [])]
        files = [o for o in resp.get("Contents", []) if o["Key"] != prefix]
        if query:
            qlower = query.lower()
            folders = [p for p in folders if qlower in p.lower()]
            files = [o for o in files if qlower in o["Key"].lower()]
        folder_count = len(folders)
        file_count = len(files)
        total_size = sum([o.get("Size", 0) for o in files])
        latest_modified = None
        for o in files:
            lm = o.get("LastModified")
            if lm and (latest_modified is None or lm > latest_modified):
                latest_modified = lm
        next_token = resp.get("NextContinuationToken", "")

        folder_rows = ""
        folder_cards = ""
        for pref in folders:
            name = pref[len(prefix):].strip("/")
            safe_name = html.escape(name)
            safe_key = html.escape(pref)
            safe_uri = html.escape(f"s3://{config['bucket']}/{pref}")
            folder_rows += f"""
            <tr data-kind="folder" data-name="{safe_name}" data-size="0" data-date="" data-key="{safe_key}">
              <td class='col-select'><input class='checkbox row-select' type='checkbox' data-key="{safe_key}"></td>
              <td>
                <span class='tag-folder'>
                  <span class='folder-icon'></span>
                  <span>{safe_name}</span>
                </span>
              </td>
              <td class='meta'>Folder</td>
              <td class='size'>--</td>
              <td class='meta'>--</td>
              <td class='actions'>
                <a class='link' href='/?prefix={urllib.parse.quote(pref)}'>Open</a>
                <a class='link' href='#' data-rename='{safe_key}' data-name='{safe_name}'>Rename</a>
                <a class='link danger' href='/delete?file={urllib.parse.quote(pref)}&prefix={urllib.parse.quote(prefix)}' data-delete-url='/delete?file={urllib.parse.quote(pref)}&prefix={urllib.parse.quote(prefix)}'>Delete</a>
                <a class='action-link' href='#' data-copy='{safe_uri}'>Copy URI</a>
              </td>
            </tr>
            """
            folder_cards += f"""
            <div class='grid-item' data-kind="folder" data-name="{safe_name}" data-size="0" data-date="" data-key="{safe_key}">
              <div class='grid-head'>
                <span class='folder-icon'></span>
                <div class='grid-title'>{safe_name}</div>
              </div>
              <div class='grid-meta'>
                <span class='meta-pill'>Folder</span>
                <span class='meta-pill'>--</span>
              </div>
              <div class='grid-actions'>
                <a class='action-link' href='/?prefix={urllib.parse.quote(pref)}'>Open</a>
                <a class='action-link' href='#' data-rename='{safe_key}' data-name='{safe_name}'>Rename</a>
                <a class='action-link' href='#' data-copy='{safe_uri}'>Copy URI</a>
                <a class='action-link link danger' href='/delete?file={urllib.parse.quote(pref)}&prefix={urllib.parse.quote(prefix)}' data-delete-url='/delete?file={urllib.parse.quote(pref)}&prefix={urllib.parse.quote(prefix)}'>Delete</a>
              </div>
              <label class='meta-pill'><input class='checkbox row-select' type='checkbox' data-key="{safe_key}"> Select</label>
            </div>
            """

        file_rows = ""
        file_cards = ""
        for o in files:
            name = o["Key"][len(prefix):] if prefix and o["Key"].startswith(prefix) else o["Key"]
            ext = os.path.splitext(name)[1].replace(".", "").upper() or "FILE"
            modified = o.get("LastModified", "")
            modified_iso = modified.isoformat() if hasattr(modified, "isoformat") else ""
            safe_name = html.escape(name)
            safe_key = html.escape(o["Key"])
            safe_ext = html.escape(ext)
            safe_uri = html.escape(f"s3://{config['bucket']}/{o['Key']}")
            file_rows += f"""
            <tr data-kind="file" data-name="{safe_name}" data-size="{o.get('Size', 0)}" data-date="{modified_iso}" data-key="{safe_key}">
              <td class='col-select'><input class='checkbox row-select' type='checkbox' data-key="{safe_key}"></td>
              <td><span class='file-icon'></span>{safe_name}</td>
              <td class='meta'>{safe_ext}</td>
              <td class='size'>{self.format_size(o.get("Size", 0))}</td>
              <td class='meta'>{self.format_date(modified)}</td>
              <td class='actions'>
                <a class='link' href='/download?file={urllib.parse.quote(o["Key"])}'>Download</a>
                <a class='link' href='/preview?file={urllib.parse.quote(o["Key"])}&prefix={urllib.parse.quote(prefix)}' target='_blank'>Preview</a>
                <a class='link' href='/presign?file={urllib.parse.quote(o["Key"])}&prefix={urllib.parse.quote(prefix)}' target='_blank'>Share</a>
                <a class='link' href='#' data-rename='{safe_key}' data-name='{safe_name}'>Rename</a>
                <a class='link danger' href='/delete?file={urllib.parse.quote(o["Key"])}&prefix={urllib.parse.quote(prefix)}' data-delete-url='/delete?file={urllib.parse.quote(o["Key"])}&prefix={urllib.parse.quote(prefix)}'>Delete</a>
                <a class='action-link' href='#' data-copy='{safe_uri}'>Copy URI</a>
              </td>
            </tr>
            """
            file_cards += f"""
            <div class='grid-item' data-kind="file" data-name="{safe_name}" data-size="{o.get('Size', 0)}" data-date="{modified_iso}" data-key="{safe_key}">
              <div class='grid-head'>
                <span class='file-icon'></span>
                <div class='grid-title'>{safe_name}</div>
              </div>
              <div class='grid-meta'>
                <span class='meta-pill'>{safe_ext}</span>
                <span class='meta-pill'>{self.format_size(o.get("Size", 0))}</span>
                <span class='meta-pill'>{self.format_date(modified)}</span>
              </div>
              <div class='grid-actions'>
                <a class='action-link' href='/download?file={urllib.parse.quote(o["Key"])}'>Download</a>
                <a class='action-link' href='/preview?file={urllib.parse.quote(o["Key"])}&prefix={urllib.parse.quote(prefix)}' target='_blank'>Preview</a>
                <a class='action-link' href='/presign?file={urllib.parse.quote(o["Key"])}&prefix={urllib.parse.quote(prefix)}' target='_blank'>Share</a>
                <a class='action-link' href='#' data-rename='{safe_key}' data-name='{safe_name}'>Rename</a>
                <a class='action-link' href='#' data-copy='{safe_uri}'>Copy URI</a>
                <a class='action-link link danger' href='/delete?file={urllib.parse.quote(o["Key"])}&prefix={urllib.parse.quote(prefix)}' data-delete-url='/delete?file={urllib.parse.quote(o["Key"])}&prefix={urllib.parse.quote(prefix)}'>Delete</a>
              </div>
              <label class='meta-pill'><input class='checkbox row-select' type='checkbox' data-key="{safe_key}"> Select</label>
            </div>
            """

        rows = folder_rows + file_rows
        if not rows:
            rows = "<tr><td colspan='6' class='empty'>No files in this folder</td></tr>"
        grid_items = folder_cards + file_cards
        if not grid_items:
            grid_items = "<div class='empty'>No files in this folder</div>"

        prefix_label = "/" if not prefix else "/" + prefix.strip("/")
        safe_prefix_label = html.escape(prefix_label)
        safe_prefix = html.escape(prefix)
        safe_bucket = html.escape(config["bucket"])
        crumbs_html = ""
        for i, (name, path) in enumerate(crumbs):
            cls = "crumb current" if i == len(crumbs) - 1 else "crumb"
            target = f"/?prefix={urllib.parse.quote(path)}" if path else "/"
            crumbs_html += f"<a class='{cls}' href='{target}'>{html.escape(name)}</a>"
        latest_label = self.format_date(latest_modified) if latest_modified else "--"
        region_label = (config.get("aws") or {}).get("region", "--")
        safe_region = html.escape(region_label)
        stats_html = f"""
        <div class='stat-grid'>
          <div class='stat-card'>
            <div class='label'>Objects</div>
            <div class='value'>{file_count + folder_count}</div>
            <div class='meta'>{file_count} files, {folder_count} folders</div>
          </div>
          <div class='stat-card'>
            <div class='label'>Total Size</div>
            <div class='value'>{self.format_size(total_size)}</div>
            <div class='meta'>Current prefix size</div>
          </div>
          <div class='stat-card'>
            <div class='label'>Latest Modified</div>
            <div class='value'>{latest_label}</div>
            <div class='meta'>Most recent file</div>
          </div>
          <div class='stat-card'>
            <div class='label'>Region</div>
            <div class='value'>{safe_region}</div>
            <div class='meta'>AWS region</div>
          </div>
        </div>
        """
        query_param = f"&q={urllib.parse.quote(query)}" if query else ""
        max_param = f"&max={max_keys}"
        next_html = ""
        if next_token:
            next_url = f"/?prefix={urllib.parse.quote(prefix)}&token={urllib.parse.quote(next_token)}{max_param}{query_param}"
            next_html = f"<div class='pager'><a class='action-link' href='{next_url}'>Next page</a></div>"
        safe_query = html.escape(query)
        safe_prefix_uri = html.escape(f"s3://{config['bucket']}/{prefix}")

        page_html = f"""
        <html><head>{self.fonts()}{self.css()}{self.scripts()}</head>
        <body data-theme="dark">
          <div class='bg-orb orb-1'></div>
          <div class='bg-orb orb-2'></div>
          <div class='bg-orb orb-3'></div>
          <div class='page'>
          <div class='top'>
              <div class='brand'>
                <div class='brand-mark'>S3</div>
                <div>
                  S3 File Manager
                <span class='chip'>{safe_bucket}</span>
                </div>
              </div>
            <div class='right-actions'>
              <span class='badge-prefix'>{safe_prefix_label}</span>
              <span class='chip'><span class='status-dot'></span>Connected</span>
              <span class='chip'>Last refresh <span id='lastRefresh'>--</span></span>
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
                <div class='toolbar-group'>
                  <form id='searchForm' method='get' action='/'>
                    <input type='hidden' name='prefix' value='{safe_prefix}'>
                    <input type='hidden' name='max' value='{max_keys}'>
                    <input id='searchBox' name='q' class='input' placeholder='Search files or folders...' value='{safe_query}'>
                  </form>
                  <select id='typeFilter' class='input' style='max-width:150px'>
                    <option value='all'>All</option>
                    <option value='file'>Files</option>
                    <option value='folder'>Folders</option>
                  </select>
                  <select id='sortSelect' class='input' style='max-width:180px'>
                    <option value='name'>Sort: Name</option>
                    <option value='size'>Sort: Size</option>
                    <option value='modified'>Sort: Modified</option>
                  </select>
                  <div class='view-toggle'>
                    <button id='viewTable' class='btn ghost' type='button'>List</button>
                    <button id='viewGrid' class='btn ghost' type='button'>Grid</button>
                  </div>
                </div>
                <div class='toolbar-group'>
                  <a class='action-link' href='/?prefix={urllib.parse.quote(prefix)}{query_param}{max_param}'>Refresh</a>
                  <a class='action-link' href='#' data-copy='{safe_prefix_uri}'>Copy Prefix</a>
                </div>
              </div>
              <div class='section-title'>Bulk Actions</div>
              <div id='bulkBar' class='bulk-bar hidden'>
                <span id='selectedCount' class='muted'>0 selected</span>
                <input id='bulkTarget' class='input bulk-input' form='bulkForm' placeholder='Target prefix (e.g. archive/)'>
                <button id='bulkMove' class='btn secondary' type='button'>Move</button>
                <button id='bulkCopy' class='btn secondary' type='button'>Copy</button>
                <button id='bulkDelete' class='btn warn' type='button'>Delete</button>
              </div>

              <div class='section-title'>Files</div>
              <form id='bulkForm' method='post' action='/bulk-action'>
                <input id='bulkAction' type='hidden' name='action' value=''>
                <input type='hidden' name='prefix' value='{safe_prefix}'>
                <input id='bulkTargetHidden' type='hidden' name='target' value=''>
              </form>
              <form id='renameForm' method='post' action='/rename'>
                <input type='hidden' name='old' value=''>
                <input type='hidden' name='new' value=''>
                <input type='hidden' name='prefix' value='{safe_prefix}'>
              </form>

              <div class='table-scroll'>
                <table id='fileTable'>
                  <thead>
                    <tr>
                      <th class='col-select'><input id='selectAll' class='checkbox' type='checkbox'></th>
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
              <div id='gridItems' class='grid'>
                {grid_items}
              </div>
              {next_html}

              <div class='uploadbox'>
                <form id='uploadForm' method='post' enctype='multipart/form-data'>
                  <input type='hidden' name='prefix' value='{safe_prefix}'>
                  <div id='dropzone' class='dropzone'>
                    <div>
                      <div style='font-weight:600'>Drag & drop files</div>
                      <div class='muted' style='font-size:12px'>or pick files to upload</div>
                      <div id='fileCount' class='muted' style='font-size:12px'>No files selected</div>
                    </div>
                    <div>
                      <input id='fileInput' type='file' name='file' multiple>
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
                  <input type='hidden' name='prefix' value='{safe_prefix}'>
                  <input class='input' style='max-width:220px' name='folder' placeholder='New folder name'>
                  <button class='btn secondary' type='submit'>Create Folder</button>
                </form>
              </div>
            </div>
          </div>
          <div id='toast' class='toast'></div>
          <div id='confirmModal' class='modal-backdrop'>
            <div class='modal'>
              <h3 id='confirmTitle'>Confirm</h3>
              <p id='confirmMessage'>Are you sure?</p>
              <input id='confirmInput' class='is-hidden' type='text'>
              <div class='modal-actions'>
                <button id='confirmCancel' class='btn ghost' type='button'>Cancel</button>
                <button id='confirmOk' class='btn warn' type='button'>Delete</button>
              </div>
            </div>
          </div>
          </div>
        </body></html>
        """
        self.respond(page_html)

    # ===== POST =====
    def do_POST(self):
        global config, s3
        if not self.is_authenticated():
            return self.send_auth_required()

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
            back = f"/?prefix={urllib.parse.quote(prefix)}" if prefix else "/"
            return self.respond(f"<script>location='{back}'</script>")

        if self.path == "/bulk-action":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            action = form.get("action", [""])[0]
            keys = form.get("keys", [])
            target = form.get("target", [""])[0].strip()
            back_prefix = form.get("prefix", [""])[0]
            back = f"/?prefix={urllib.parse.quote(back_prefix)}" if back_prefix else "/"
            if action in ["move", "copy"] and target and not target.endswith("/"):
                target += "/"
            if action == "delete":
                for key in keys:
                    if key.endswith("/"):
                        token = ""
                        while True:
                            args = {"Bucket": config["bucket"], "Prefix": key}
                            if token:
                                args["ContinuationToken"] = token
                            resp = s3.list_objects_v2(**args)
                            for obj in resp.get("Contents", []):
                                s3.delete_object(Bucket=config["bucket"], Key=obj["Key"])
                            if not resp.get("IsTruncated"):
                                break
                            token = resp.get("NextContinuationToken", "")
                    else:
                        s3.delete_object(Bucket=config["bucket"], Key=key)
                return self.respond(f"<script>location='{back}'</script>")
            if action in ["move", "copy"] and target:
                for key in keys:
                    if key.endswith("/"):
                        name = key.rstrip("/").split("/")[-1] + "/"
                        new_prefix = target + name
                        self.copy_prefix(key, new_prefix, delete_source=(action == "move"))
                    else:
                        new_key = target + os.path.basename(key)
                        s3.copy_object(
                            Bucket=config["bucket"],
                            CopySource={"Bucket": config["bucket"], "Key": key},
                            Key=new_key
                        )
                        if action == "move":
                            s3.delete_object(Bucket=config["bucket"], Key=key)
                return self.respond(f"<script>location='{back}'</script>")
            return self.respond("<html><body>Bulk action failed</body></html>")

        if self.path == "/rename":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            old_key = form.get("old", [""])[0]
            new_name = form.get("new", [""])[0].strip()
            back_prefix = form.get("prefix", [""])[0]
            back = f"/?prefix={urllib.parse.quote(back_prefix)}" if back_prefix else "/"
            if not old_key or not new_name:
                return self.respond(f"<script>location='{back}'</script>")
            is_folder = old_key.endswith("/")
            if "/" in new_name:
                new_key = new_name
            else:
                parent = old_key.rstrip("/").rsplit("/", 1)
                if len(parent) == 2:
                    new_key = parent[0] + "/" + new_name
                else:
                    new_key = new_name
            if is_folder and not new_key.endswith("/"):
                new_key += "/"
            if is_folder:
                self.copy_prefix(old_key, new_key, delete_source=True)
            else:
                s3.copy_object(
                    Bucket=config["bucket"],
                    CopySource={"Bucket": config["bucket"], "Key": old_key},
                    Key=new_key
                )
                s3.delete_object(Bucket=config["bucket"], Key=old_key)
            return self.respond(f"<script>location='{back}'</script>")

        # Handle upload (including prefix when provided)
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0")
                }
            )
            file_item = form["file"] if "file" in form else None
            prefix = ""
            if "prefix" in form and form["prefix"].value:
                prefix = form["prefix"].value
            if prefix and not prefix.endswith("/"):
                prefix = prefix + "/"
            if file_item is None:
                return self.respond_text(400, "Upload failed: no file")
            items = file_item if isinstance(file_item, list) else [file_item]
            for item in items:
                if not getattr(item, "filename", ""):
                    continue
                filename = os.path.basename(item.filename)
                if not filename:
                    continue
                key = (prefix or "") + filename
                s3.upload_fileobj(item.file, config["bucket"], key)
            back = f"/?prefix={urllib.parse.quote(prefix)}" if prefix else "/"
            return self.respond(f"<script>location='{back}'</script>")
        except Exception as e:
            sys.stderr.write(f"Upload failed: {e}\n")
            return self.respond_text(500, f"Upload failed: {e}")


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
