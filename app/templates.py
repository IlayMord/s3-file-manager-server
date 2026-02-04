"""Template loader for S3 File Manager."""

from pathlib import Path

_BASE_DIR = Path(__file__).parent / "templates"


def _load(name):
    return (_BASE_DIR / name).read_text(encoding="utf-8")


def _render(raw, context):
    out = raw
    for key, value in context.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out


def render_page(title, body_html):
    css = (Path(__file__).parent / "static" / "css" / "style.css").read_text(encoding="utf-8")
    js = (Path(__file__).parent / "static" / "js" / "app.js").read_text(encoding="utf-8")
    base = _load("layouts/base.html")
    return _render(base, {"title": title, "css": css, "js": js, "body": body_html})


def render_auth_form(title, subtitle, action, fields, error_html, switch_html):
    body = _render(
        _load("pages/auth.html"),
        {
            "auth_title": title,
            "auth_subtitle": subtitle,
            "auth_action": action,
            "fields_html": "".join(fields),
            "error_html": error_html,
            "switch_html": switch_html,
        },
    )
    return render_page(title, body)


def render_bucket_form(error_html):
    body = _render(_load("pages/bucket.html"), {"error_html": error_html})
    return render_page("Connect Bucket", body)


def render_creds_form(error_html):
    body = _render(_load("pages/creds.html"), {"error_html": error_html})
    return render_page("AWS Credentials", body)


def render_main_page(content_html):
    body = _render(_load("pages/main.html"), {"content": content_html})
    return render_page("S3 File Manager", body)


def render_presign(safe_key, safe_url, back_url):
    body = _render(
        _load("pages/presign.html"),
        {"safe_key": safe_key, "safe_url": safe_url, "back_url": back_url},
    )
    return render_page("Share Link", body)


def render_preview(safe_key, embed_html, back_url, download_url):
    body = _render(
        _load("pages/preview.html"),
        {
            "safe_key": safe_key,
            "embed_html": embed_html,
            "back_url": back_url,
            "download_url": download_url,
        },
    )
    return render_page("Preview", body)
