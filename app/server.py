#!/usr/bin/env python3

import http.server, socketserver, urllib.parse, cgi
import base64
import html
import mimetypes
import time
import os
import sys
import logging
import secrets
import hashlib
import datetime
import boto3, json
from cryptography.fernet import Fernet
sys.path.insert(0, os.path.dirname(__file__))
import templates
import psycopg2
import psycopg2.extras

def resolve_port():
    try:
        return int(os.getenv("S3FM_PORT", "8000"))
    except Exception:
        return 8000


def resolve_config_dir():
    env_dir = os.getenv("S3FM_CONFIG_DIR")
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
SECRET_FILE = os.path.join(CONFIG_DIR, "secret.key")
LOG_DIR = os.path.join(CONFIG_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
DB_URL = os.getenv("S3FM_DB_URL", "postgresql://postgres:postgres@localhost:5432/s3_file_manager")
SESSION_DAYS = 7


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

def get_db_conn():
    return psycopg2.connect(DB_URL)

def init_auth_db():
    for attempt in range(12):
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS users (
                          id SERIAL PRIMARY KEY,
                          email TEXT UNIQUE NOT NULL,
                          password_hash TEXT NOT NULL,
                          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sessions (
                          id SERIAL PRIMARY KEY,
                          token TEXT UNIQUE NOT NULL,
                          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                          expires_at TIMESTAMPTZ NOT NULL
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS app_settings (
                          user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                          bucket TEXT,
                          aws_access_key TEXT,
                          aws_secret_key TEXT,
                          aws_region TEXT
                        )
                        """
                    )
                    cur.execute(
                        """
                        DO $$
                        BEGIN
                          IF EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = 'app_settings' AND column_name = 'id'
                          ) AND NOT EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = 'app_settings' AND column_name = 'user_id'
                          ) THEN
                            ALTER TABLE app_settings RENAME COLUMN id TO user_id;
                          END IF;
                        END $$;
                        """
                    )
                    cur.execute(
                        """
                        DO $$
                        BEGIN
                          IF NOT EXISTS (
                            SELECT 1
                            FROM information_schema.table_constraints
                            WHERE table_name = 'app_settings'
                              AND constraint_name = 'app_settings_user_id_fkey'
                          ) THEN
                            ALTER TABLE app_settings
                            ADD CONSTRAINT app_settings_user_id_fkey
                            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                          END IF;
                        EXCEPTION
                          WHEN duplicate_object THEN NULL;
                        END $$;
                        """
                    )
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Failed to connect to Postgres for auth DB initialization.")

def get_app_settings(user_id):
    with get_db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT bucket, aws_access_key, aws_secret_key, aws_region
                FROM app_settings
                WHERE user_id = %s
                """
                ,
                (user_id,)
            )
            return cur.fetchone()

def upsert_app_settings(user_id, bucket=None, aws=None):
    existing = get_app_settings(user_id) or {}
    if bucket is None:
        bucket = existing.get("bucket")
    if aws is None:
        aws_access_key = existing.get("aws_access_key")
        aws_secret_key = existing.get("aws_secret_key")
        aws_region = existing.get("aws_region")
    else:
        aws_access_key = aws.get("access_key")
        aws_secret_key = aws.get("secret_key")
        aws_region = aws.get("region")
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_settings (user_id, bucket, aws_access_key, aws_secret_key, aws_region)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                  bucket = EXCLUDED.bucket,
                  aws_access_key = EXCLUDED.aws_access_key,
                  aws_secret_key = EXCLUDED.aws_secret_key,
                  aws_region = EXCLUDED.aws_region
                """,
                (user_id, bucket, aws_access_key, aws_secret_key, aws_region),
            )
        conn.commit()

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return base64.b64encode(salt + digest).decode()

def verify_password(password, stored):
    try:
        data = base64.b64decode(stored.encode())
        salt = data[:16]
        digest = data[16:]
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return secrets.compare_digest(check, digest)
    except Exception:
        return False

def parse_cookies(cookie_header):
    cookies = {}
    if not cookie_header:
        return cookies
    parts = cookie_header.split(";")
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies

def get_user_by_session(token):
    if not token:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    with get_db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
            """
            SELECT users.id, users.email, sessions.expires_at
            FROM sessions JOIN users ON sessions.user_id = users.id
            WHERE sessions.token = %s
            """,
            (token,),
            )
            row = cur.fetchone()
            if not row:
                return None
            if row["expires_at"] < now:
                cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
                conn.commit()
                return None
            return {"id": row["id"], "email": row["email"]}

def create_session(user_id):
    token = secrets.token_urlsafe(32)
    now = datetime.datetime.now(datetime.timezone.utc)
    expires = now + datetime.timedelta(days=SESSION_DAYS)
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
            """
            INSERT INTO sessions (token, user_id, created_at, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (token, user_id, now, expires),
            )
            conn.commit()
    return token, expires

def delete_session(token):
    if not token:
        return
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
            conn.commit()


# ENCRYPTION
def load_or_create_secret():
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SECRET_FILE, "wb") as f:
        f.write(key)
    return key

FERNET = Fernet(load_or_create_secret())

def encrypt(text):
    return FERNET.encrypt(text.encode()).decode()

def decrypt(token):
    try:
        return FERNET.decrypt(token.encode()).decode()
    except Exception:
        # Backwards compatibility for configs saved before encryption.
        return token


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
            aws_access_key_id=decrypt(aws["access_key"]),
            aws_secret_access_key=decrypt(aws["secret_key"]),
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
    def render_bucket_form(self, error=""):
        error_html = f"<div class='subtitle error'>{error}</div>" if error else ""
        return templates.render_bucket_form(error_html)

    def render_creds_form(self, error=""):
        error_html = f"<div class='subtitle error'>{error}</div>" if error else ""
        return templates.render_creds_form(error_html)

    # ===== JavaScript: theme toggling, search, and upload progress =====
    def respond(self, html):
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def redirect_to_prefix(self, prefix="", query=""):
        location = f"/?prefix={urllib.parse.quote(prefix)}" if prefix else "/"
        if query:
            sep = "&" if "?" in location else "?"
            location += f"{sep}q={urllib.parse.quote(query)}"
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def respond_text(self, status, text, content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def respond_json(self, status, payload):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def current_user(self):
        cookies = parse_cookies(self.headers.get("Cookie", ""))
        token = cookies.get("s3fm_session")
        return get_user_by_session(token)

    def get_runtime_config(self, user=None):
        runtime_config = dict(config)
        if not user:
            return runtime_config
        settings = get_app_settings(user["id"]) or {}
        runtime_config.pop("bucket", None)
        runtime_config.pop("aws", None)
        if settings.get("bucket"):
            runtime_config["bucket"] = settings["bucket"]
        if settings.get("aws_access_key") and settings.get("aws_secret_key") and settings.get("aws_region"):
            runtime_config["aws"] = {
                "access_key": settings["aws_access_key"],
                "secret_key": settings["aws_secret_key"],
                "region": settings["aws_region"],
            }
        return runtime_config

    def get_runtime_s3(self, runtime_config):
        return build_s3(runtime_config) if runtime_config.get("aws") else None

    def require_auth(self):
        public = {"/login", "/register"}
        path = urllib.parse.urlparse(self.path).path
        if path in public:
            return True
        user = self.current_user()
        if user:
            return True
        self.send_response(302)
        self.send_header("Location", "/login")
        self.end_headers()
        return False

    def serve_static(self, path):
        static_root = os.path.join(os.path.dirname(__file__), "static")
        rel = path[len("/static/"):]
        rel = os.path.normpath(rel).lstrip(os.sep)
        static_root_abs = os.path.abspath(static_root)
        file_path = os.path.abspath(os.path.join(static_root, rel))
        if not (file_path == static_root_abs or file_path.startswith(static_root_abs + os.sep)):
            return self.respond_text(404, "Not found")
        if not os.path.isfile(file_path):
            return self.respond_text(404, "Not found")
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        with open(file_path, "rb") as handle:
            self.wfile.write(handle.read())


    def presign_url(self, s3_client, bucket, key, expires=900):
        try:
            return s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires
            )
        except Exception:
            return ""

    def stream_object(self, s3_client, bucket, key, download=True, override_type=""):
        try:
            obj = s3_client.get_object(Bucket=bucket, Key=key)
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

    def copy_prefix(self, s3_client, bucket, old_prefix, new_prefix, delete_source=False):
        token = ""
        while True:
            args = {
                "Bucket": bucket,
                "Prefix": old_prefix
            }
            if token:
                args["ContinuationToken"] = token
            resp = s3_client.list_objects_v2(**args)
            for obj in resp.get("Contents", []):
                src_key = obj["Key"]
                dst_key = new_prefix + src_key[len(old_prefix):]
                s3_client.copy_object(
                    Bucket=bucket,
                    CopySource={"Bucket": bucket, "Key": src_key},
                    Key=dst_key
                )
                if delete_source:
                    s3_client.delete_object(Bucket=bucket, Key=src_key)
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken", "")

    # GET
    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(p.query)

        if p.path.startswith("/static/"):
            return self.serve_static(p.path)

        if p.path == "/healthz":
            return self.respond_json(200, {"status": "ok"})

        if p.path == "/readyz":
            try:
                with get_db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        cur.fetchone()
                return self.respond_json(200, {"status": "ready"})
            except Exception as e:
                logging.warning("Readiness check failed: %s", e)
                return self.respond_json(503, {"status": "not_ready"})

        if not self.require_auth():
            return

        if p.path == "/login":
            error_html = ""
            fields = [
                "<input class='input' name='email' placeholder='Email' type='email' required>",
                "<input class='input' name='password' placeholder='Password' type='password' required>",
            ]
            switch_html = "No account? <a class='link' href='/register'>Create one</a>"
            return self.respond(templates.render_auth_form(
                "Sign in", "Welcome back. Access your S3 workspace.", "/login", fields, error_html, switch_html
            ))

        if p.path == "/register":
            error_html = ""
            fields = [
                "<input class='input' name='email' placeholder='Email' type='email' required>",
                "<input class='input' name='password' placeholder='Password' type='password' required>",
                "<input class='input' name='password_confirm' placeholder='Confirm password' type='password' required>",
                "<input class='input' name='access_key' placeholder='AWS Access Key' required>",
                "<input class='input' name='secret_key' placeholder='AWS Secret Key' required>",
                "<input class='input' name='region' value='us-east-1' required>",
            ]
            switch_html = "Already have an account? <a class='link' href='/login'>Sign in</a>"
            return self.respond(templates.render_auth_form(
                "Create account", "Create your account and save AWS credentials once.", "/register", fields, error_html, switch_html
            ))

        if p.path == "/change-password":
            if not self.require_auth():
                return
            error_html = ""
            fields = [
                "<input class='input' name='current_password' placeholder='Current password' type='password' required>",
                "<input class='input' name='new_password' placeholder='New password' type='password' required>",
                "<input class='input' name='confirm_password' placeholder='Confirm new password' type='password' required>",
            ]
            switch_html = "Back to files? <a class='link' href='/'>Go to manager</a>"
            return self.respond(templates.render_auth_form(
                "Change password", "Update your account password.", "/change-password", fields, error_html, switch_html
            ))

        user = self.current_user()
        runtime_config = self.get_runtime_config(user)
        runtime_s3 = self.get_runtime_s3(runtime_config)

        # No bucket has been configured yet
        if not runtime_config.get("bucket"):
            return self.respond(self.render_bucket_form())

        # AWS credentials are not configured yet
        if not runtime_config.get("aws") or not runtime_s3:
            return self.respond(self.render_creds_form())

        bucket = runtime_config["bucket"]

        prefix = q.get("prefix", [""])[0]
        token = q.get("token", [""])[0]
        query = q.get("q", [""])[0].strip()
        max_keys_raw = q.get("max", ["500"])[0]
        try:
            max_keys = max(50, min(1000, int(max_keys_raw)))
        except Exception:
            max_keys = 500
        safe_prefix = html.escape(prefix)
        safe_query = html.escape(query)
        parts = [p for p in prefix.strip("/").split("/") if p] if prefix else []
        crumbs = [("Root", "")]
        current = ""
        for part in parts:
            current += part + "/"
            crumbs.append((part, current))

        if p.path == "/change-bucket":
            return self.respond(self.render_bucket_form("Enter a new bucket name to switch."))

        if p.path == "/change-creds":
            return self.respond(self.render_creds_form("Enter new AWS credentials."))

        if p.path == "/download":
            try:
                key = q.get("file", [""])[0]
                if self.stream_object(runtime_s3, bucket, key, download=True):
                    return
                return self.respond("<html><body>Download failed</body></html>")
            except Exception:
                return self.respond("<html><body>Download failed</body></html>")

        if p.path == "/download-server":
            try:
                key = q.get("file", [""])[0]
                local = f"/tmp/{os.path.basename(key)}"
                runtime_s3.download_file(bucket, key, local)
                return self.respond(f"<html><body>Downloaded to {local}</body></html>")
            except Exception:
                return self.respond("<html><body>Download failed</body></html>")

        if p.path == "/presign":
            key = q.get("file", [""])[0]
            back_prefix = q.get("prefix", [""])[0]
            back_url = f"/?prefix={urllib.parse.quote(back_prefix)}" if back_prefix else "/"
            url = self.presign_url(runtime_s3, bucket, key, expires=900)
            if not url:
                return self.respond("<html><body>Failed to create link</body></html>")
            safe_key = html.escape(key)
            safe_url = html.escape(url)
            return self.respond(templates.render_presign(safe_key, safe_url, back_url))

        if p.path == "/preview":
            key = q.get("file", [""])[0]
            back_prefix = q.get("prefix", [""])[0]
            back_url = f"/?prefix={urllib.parse.quote(back_prefix)}" if back_prefix else "/"
            ext = os.path.splitext(key)[1].lower()
            mime = mimetypes.guess_type(key)[0] or ""
            url = self.presign_url(runtime_s3, bucket, key, expires=900)
            safe_key = html.escape(key)
            if not url:
                return self.respond("<html><body>Preview failed</body></html>")
            embed = ""
            if mime.startswith("image/"):
                embed = f"<img class='preview-media' src='{html.escape(url)}'>"
            elif mime.startswith("video/"):
                embed = f"<video class='preview-video' controls src='{html.escape(url)}'></video>"
            elif mime.startswith("audio/"):
                embed = f"<audio class='preview-audio' controls src='{html.escape(url)}'></audio>"
            elif ext == ".pdf":
                embed = f"<iframe class='preview-iframe' src='{html.escape(url)}'></iframe>"
            elif mime.startswith("text/") or ext in [".log", ".md", ".json", ".txt", ".csv"]:
                try:
                    obj = runtime_s3.get_object(Bucket=bucket, Key=key)
                    body = obj["Body"].read(200000).decode("utf-8", errors="replace")
                    embed = f"<pre class='preview-frame mono'>{html.escape(body)}</pre>"
                except Exception:
                    embed = "<div class='preview-frame'>Unable to load text preview.</div>"
            else:
                embed = f"<div class='preview-frame'>Preview not supported. <a class='action-link' href='{html.escape(url)}' target='_blank'>Open file</a></div>"
            download_url = f"/download?file={urllib.parse.quote(key)}"
            return self.respond(templates.render_preview(safe_key, embed, back_url, download_url))

        # List objects with folder-style prefixes
        try:
            list_args = {
                "Bucket": bucket,
                "Prefix": prefix if prefix else "",
                "Delimiter": "/",
                "MaxKeys": max_keys
            }
            if token:
                list_args["ContinuationToken"] = token
            resp = runtime_s3.list_objects_v2(**list_args)
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
            safe_uri = html.escape(f"s3://{bucket}/{pref}")
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
                <form method='post' action='/delete' class='inline-form'>
                  <input type='hidden' name='file' value='{safe_key}'>
                  <input type='hidden' name='prefix' value='{safe_prefix}'>
                  <input type='hidden' name='q' value='{safe_query}'>
                  <button class='link danger' type='submit'>Delete</button>
                </form>
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
                <form method='post' action='/delete' class='inline-form'>
                  <input type='hidden' name='file' value='{safe_key}'>
                  <input type='hidden' name='prefix' value='{safe_prefix}'>
                  <input type='hidden' name='q' value='{safe_query}'>
                  <button class='action-link link danger' type='submit'>Delete</button>
                </form>
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
            safe_uri = html.escape(f"s3://{bucket}/{o['Key']}")
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
                <form method='post' action='/delete' class='inline-form'>
                  <input type='hidden' name='file' value='{safe_key}'>
                  <input type='hidden' name='prefix' value='{safe_prefix}'>
                  <input type='hidden' name='q' value='{safe_query}'>
                  <button class='link danger' type='submit'>Delete</button>
                </form>
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
                <form method='post' action='/delete' class='inline-form'>
                  <input type='hidden' name='file' value='{safe_key}'>
                  <input type='hidden' name='prefix' value='{safe_prefix}'>
                  <input type='hidden' name='q' value='{safe_query}'>
                  <button class='action-link link danger' type='submit'>Delete</button>
                </form>
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
        user = self.current_user() or {}
        safe_email = html.escape(user.get("email", ""))
        safe_bucket = html.escape(bucket)
        crumbs_html = ""
        for i, (name, path) in enumerate(crumbs):
            cls = "crumb current" if i == len(crumbs) - 1 else "crumb"
            target = f"/?prefix={urllib.parse.quote(path)}" if path else "/"
            crumbs_html += f"<a class='{cls}' href='{target}'>{html.escape(name)}</a>"
        latest_label = self.format_date(latest_modified) if latest_modified else "--"
        region_label = (runtime_config.get("aws") or {}).get("region", "--")
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
        safe_prefix_uri = html.escape(f"s3://{bucket}/{prefix}")

        page_html = f"""
          <div class='top'>
              <div class='brand'>
                <div class='brand-mark'>S3</div>
                <div>
                  S3 File Manager
                <span class='chip'>{safe_email}</span>
                </div>
              </div>
            <div class='right-actions'>
              <span class='badge-prefix'>{safe_prefix_label}</span>
              <span class='chip'><span class='status-dot'></span>Connected</span>
              <span class='chip'>Last refresh <span id='lastRefresh'>--</span></span>
              <span class='pill-ghost'>Bucket: {safe_bucket}</span>
              <div class='link-group'>
                <a href='/change-bucket'>Bucket</a>
                <a href='/change-creds'>Credentials</a>
                <a href='/change-password'>Password</a>
              </div>
              <form method='post' action='/logout' class='inline-form'>
                <button class='danger' type='submit'>Logout</button>
              </form>
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
                  <select id='typeFilter' class='input w-150'>
                    <option value='all'>All</option>
                    <option value='file'>Files</option>
                    <option value='folder'>Folders</option>
                  </select>
                  <select id='sortSelect' class='input w-180'>
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
                      <div class='dropzone-title'>Drag & drop files</div>
                      <div class='muted small'>or pick files to upload</div>
                      <div id='fileCount' class='muted small'>No files selected</div>
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
                  <div id='progressWrap' class='progress-wrap is-hidden'>
                    <div class='progress-bar'>
                      <div id='progressFill' class='progress-fill'></div>
                    </div>
                    <div id='progressText' class='progress-text'>0%</div>
                  </div>
                </form>

                <form class='folder-form' method='post' action='/create-folder'>
                  <input type='hidden' name='prefix' value='{safe_prefix}'>
                  <input class='input w-220' name='folder' placeholder='New folder name'>
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
        """
        self.respond(templates.render_main_page(page_html))

    # POST 
    def do_POST(self):
        if self.path in ["/login", "/register"]:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            email = form.get("email", [""])[0].strip().lower()
            password = form.get("password", [""])[0]
            if self.path == "/register":
                confirm = form.get("password_confirm", [""])[0]
                access_key = form.get("access_key", [""])[0].strip()
                secret_key = form.get("secret_key", [""])[0].strip()
                region = form.get("region", ["us-east-1"])[0].strip()
                if not email or not password or not access_key or not secret_key or not region:
                    error_html = "<div class='subtitle error'>All fields are required.</div>"
                elif password != confirm:
                    error_html = "<div class='subtitle error'>Passwords do not match.</div>"
                else:
                    try:
                        with get_db_conn() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "INSERT INTO users (email, password_hash, created_at) VALUES (%s, %s, %s) RETURNING id",
                                    (email, hash_password(password), datetime.datetime.now(datetime.timezone.utc)),
                                )
                                user_id = cur.fetchone()[0]
                            conn.commit()
                        config["aws"] = {
                            "access_key": encrypt(access_key),
                            "secret_key": encrypt(secret_key),
                            "region": region,
                        }
                        upsert_app_settings(user_id, aws={
                            "access_key": encrypt(access_key),
                            "secret_key": encrypt(secret_key),
                            "region": region,
                        })
                        token, _ = create_session(user_id)
                        self.send_response(302)
                        cookie = f"s3fm_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"
                        self.send_header("Set-Cookie", cookie)
                        self.send_header("Location", "/")
                        self.end_headers()
                        return
                    except psycopg2.IntegrityError:
                        error_html = "<div class='subtitle error'>Email already exists.</div>"
                fields = [
                    "<input class='input' name='email' placeholder='Email' type='email' required>",
                    "<input class='input' name='password' placeholder='Password' type='password' required>",
                    "<input class='input' name='password_confirm' placeholder='Confirm password' type='password' required>",
                    "<input class='input' name='access_key' placeholder='AWS Access Key' required>",
                    "<input class='input' name='secret_key' placeholder='AWS Secret Key' required>",
                    "<input class='input' name='region' value='us-east-1' required>",
                ]
                switch_html = "Already have an account? <a class='link' href='/login'>Sign in</a>"
                return self.respond(templates.render_auth_form(
                    "Create account", "Create your account and save AWS credentials once.", "/register", fields, error_html, switch_html
                ))

            if not email or not password:
                error_html = "<div class='subtitle error'>Email and password are required.</div>"
            else:
                with get_db_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
                        user = cur.fetchone()
                if user and verify_password(password, user["password_hash"]):
                    token, _ = create_session(user["id"])
                    self.send_response(302)
                    cookie = f"s3fm_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"
                    self.send_header("Set-Cookie", cookie)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                error_html = "<div class='subtitle error'>Invalid credentials.</div>"
            fields = [
                "<input class='input' name='email' placeholder='Email' type='email' required>",
                "<input class='input' name='password' placeholder='Password' type='password' required>",
            ]
            switch_html = "No account? <a class='link' href='/register'>Create one</a>"
            return self.respond(templates.render_auth_form(
                "Sign in", "Welcome back. Access your S3 workspace.", "/login", fields, error_html, switch_html
            ))

        if self.path == "/change-password":
            if not self.require_auth():
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            current_password = form.get("current_password", [""])[0]
            new_password = form.get("new_password", [""])[0]
            confirm_password = form.get("confirm_password", [""])[0]
            user = self.current_user()
            error_html = ""
            if not current_password or not new_password or not confirm_password:
                error_html = "<div class='subtitle error'>All fields are required.</div>"
            elif new_password != confirm_password:
                error_html = "<div class='subtitle error'>New passwords do not match.</div>"
            else:
                with get_db_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute("SELECT id, password_hash FROM users WHERE id = %s", (user["id"],))
                        row = cur.fetchone()
                        if not row or not verify_password(current_password, row["password_hash"]):
                            error_html = "<div class='subtitle error'>Current password is incorrect.</div>"
                        else:
                            cur.execute(
                                "UPDATE users SET password_hash = %s WHERE id = %s",
                                (hash_password(new_password), user["id"]),
                            )
                            conn.commit()
                            self.send_response(302)
                            self.send_header("Location", "/")
                            self.end_headers()
                            return
            fields = [
                "<input class='input' name='current_password' placeholder='Current password' type='password' required>",
                "<input class='input' name='new_password' placeholder='New password' type='password' required>",
                "<input class='input' name='confirm_password' placeholder='Confirm new password' type='password' required>",
            ]
            switch_html = "Back to files? <a class='link' href='/'>Go to manager</a>"
            return self.respond(templates.render_auth_form(
                "Change password", "Update your account password.", "/change-password", fields, error_html, switch_html
            ))

        if not self.require_auth():
            return
        user = self.current_user()
        runtime_config = self.get_runtime_config(user)
        runtime_s3 = self.get_runtime_s3(runtime_config)
        bucket = runtime_config.get("bucket")
        if self.path == "/logout":
            cookies = parse_cookies(self.headers.get("Cookie", ""))
            token = cookies.get("s3fm_session")
            delete_session(token)
            self.send_response(302)
            self.send_header("Set-Cookie", "s3fm_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if self.path == "/delete":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            key = form.get("file", [""])[0]
            prefix = form.get("prefix", [""])[0]
            query = form.get("q", [""])[0].strip()
            if not key:
                return self.redirect_to_prefix(prefix, query)
            try:
                if not runtime_s3 or not bucket:
                    return self.respond("<html><body>Delete failed</body></html>")
                runtime_s3.delete_object(Bucket=bucket, Key=key)
                logging.info("Delete object key=%s bucket=%s", key, bucket)
            except Exception:
                logging.exception("Delete failed")
                return self.respond("<html><body>Delete failed</body></html>")
            return self.redirect_to_prefix(prefix, query)
        if self.path == "/save-bucket":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            bucket = form.get("bucket", [""])[0].strip()
            if not bucket:
                return self.respond(self.render_bucket_form("Bucket name is required."))
            upsert_app_settings(user["id"], bucket=bucket)
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
            aws_settings = {
                "access_key": encrypt(access_key),
                "secret_key": encrypt(secret_key),
                "region": region,
            }
            test_config = dict(runtime_config)
            test_config["aws"] = aws_settings
            if not build_s3(test_config):
                return self.respond(self.render_creds_form("Credentials are invalid or incomplete."))
            upsert_app_settings(user["id"], aws=aws_settings)
            return self.respond("<script>location='/'</script>")

        if self.path == "/create-folder":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = urllib.parse.parse_qs(body)
            prefix = form.get("prefix", [""])[0]
            name = form.get("folder", [""])[0].strip()
            if name:
                if not runtime_s3 or not bucket:
                    return self.respond("<html><body>Create folder failed</body></html>")
                if not name.endswith("/"):
                    name += "/"
                key = (prefix or "") + name
                runtime_s3.put_object(Bucket=bucket, Key=key, Body=b"")
                logging.info("Create folder key=%s bucket=%s", key, bucket)
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
                if not runtime_s3 or not bucket:
                    return self.respond("<html><body>Bulk action failed</body></html>")
                for key in keys:
                    if key.endswith("/"):
                        token = ""
                        while True:
                            args = {"Bucket": bucket, "Prefix": key}
                            if token:
                                args["ContinuationToken"] = token
                            resp = runtime_s3.list_objects_v2(**args)
                            for obj in resp.get("Contents", []):
                                runtime_s3.delete_object(Bucket=bucket, Key=obj["Key"])
                            if not resp.get("IsTruncated"):
                                break
                            token = resp.get("NextContinuationToken", "")
                    else:
                        runtime_s3.delete_object(Bucket=bucket, Key=key)
                logging.info("Bulk delete count=%s bucket=%s", len(keys), bucket)
                return self.respond(f"<script>location='{back}'</script>")
            if action in ["move", "copy"] and target:
                if not runtime_s3 or not bucket:
                    return self.respond("<html><body>Bulk action failed</body></html>")
                for key in keys:
                    if key.endswith("/"):
                        name = key.rstrip("/").split("/")[-1] + "/"
                        new_prefix = target + name
                        self.copy_prefix(runtime_s3, bucket, key, new_prefix, delete_source=(action == "move"))
                    else:
                        new_key = target + os.path.basename(key)
                        runtime_s3.copy_object(
                            Bucket=bucket,
                            CopySource={"Bucket": bucket, "Key": key},
                            Key=new_key
                        )
                        if action == "move":
                            runtime_s3.delete_object(Bucket=bucket, Key=key)
                logging.info("Bulk action=%s count=%s target=%s bucket=%s", action, len(keys), target, bucket)
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
                if not runtime_s3 or not bucket:
                    return self.respond("<html><body>Rename failed</body></html>")
                self.copy_prefix(runtime_s3, bucket, old_key, new_key, delete_source=True)
            else:
                if not runtime_s3 or not bucket:
                    return self.respond("<html><body>Rename failed</body></html>")
                runtime_s3.copy_object(
                    Bucket=bucket,
                    CopySource={"Bucket": bucket, "Key": old_key},
                    Key=new_key
                )
                runtime_s3.delete_object(Bucket=bucket, Key=old_key)
            logging.info("Rename old=%s new=%s bucket=%s", old_key, new_key, bucket)
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
                if not runtime_s3 or not bucket:
                    return self.respond_text(500, "Upload failed: storage is not configured")
                runtime_s3.upload_fileobj(item.file, bucket, key)
                logging.info("Upload key=%s bucket=%s", key, bucket)
            back = f"/?prefix={urllib.parse.quote(prefix)}" if prefix else "/"
            return self.respond(f"<script>location='{back}'</script>")
        except Exception as e:
            logging.exception("Upload failed")
            return self.respond_text(500, f"Upload failed: {e}")

# HTTP SERVER 
class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

setup_logging()
init_auth_db()
try:
    with ReusableTCPServer(("", PORT), UploadHandler) as httpd:
        logging.info("Serving S3 manager on port %s (HTTP)", PORT)
        httpd.serve_forever()
except OSError as e:
    logging.error("Server failed to start on port %s: %s", PORT, e)
    sys.exit(1)
