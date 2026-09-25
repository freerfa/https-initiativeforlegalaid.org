import fcntl
import json
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple

import filetype

from dotenv import load_dotenv
from flask import Flask, Response, flash, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()  # load .env into os.environ for local dev; production uses real env vars

app = Flask(__name__)
secret_key = os.environ.get("SECRET_KEY", "")
if not secret_key or secret_key in {"change-me-to-a-long-random-string", "replace-this-with-a-strong-secret"}:
    if os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("SECRET_KEY must be set to a strong random value in production.")
    secret_key = secrets.token_hex(32)  # dev-only ephemeral key; sessions reset on restart
app.secret_key = secret_key
app.config["UPLOAD_FOLDER"] = os.path.join(app.static_folder, "uploads")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
# Persistent data lives outside the repo so redeploys/uploads survive.
# Local dev: ./ (site.db next to app.py). Render: DATA_DIR=/opt/render/project/src/data (disk).
DATA_DIR = os.environ.get("DATA_DIR", "")
DB_FILE = os.path.join(DATA_DIR, "site.db") if DATA_DIR else "site.db"
SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site_data.json")
# Persistent login: keep users logged in for 30 days (survives browser close)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)

csrf = CSRFProtect(app)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ADMIN_BOOTSTRAP_ENABLED = os.environ.get("ADMIN_BOOTSTRAP", "0") == "1"

# --- Contact-form email notification ---
# Render blocks outbound SMTP (ports 25/465/587), so notifications are sent over
# an email provider's HTTPS API on port 443. Resend is the default provider; set
# RESEND_API_KEY + MAIL_FROM + MAIL_TO to switch the notifications on. With no
# key configured the contact form still works and every enquiry is stored.
MAIL_API_URL = os.environ.get("MAIL_API_URL", "https://api.resend.com/emails")
MAIL_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "").strip()
MAIL_TO = os.environ.get("MAIL_TO", "").strip()
CONTACT_RATE_LIMIT = int(os.environ.get("CONTACT_RATE_LIMIT", "5") or "5")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def get_db_connection():
    if DATA_DIR:
        os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db() -> None:
    """Create site_data table + seed from site_data.json on first boot (fresh Render disk).

    Also merges newer seed content into an existing DB (SEED_VERSION mechanism):
    content keys are refreshed from site_data.json when the seed is newer, while
    account data (admin_users/users/admin_account) is always preserved.
    """
    if DATA_DIR:
        os.makedirs(DATA_DIR, exist_ok=True)
    conn = get_db_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS site_data (id INTEGER PRIMARY KEY, data JSON)")
    # Website enquiry inbox: one row per contact-form submission. Kept in its own
    # table (not in site_data) so content resets never touch visitor messages.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL,
            ip TEXT NOT NULL DEFAULT '',
            is_read INTEGER NOT NULL DEFAULT 0,
            mail_status TEXT NOT NULL DEFAULT 'not_sent'
        )
        """
    )
    row = conn.execute("SELECT data FROM site_data WHERE id = 1").fetchone()
    seed = "{}"
    try:
        with open(SEED_FILE, "r", encoding="utf-8") as f:
            seed = f.read()
    except OSError:
        pass
    try:
        seed_obj = json.loads(seed)
    except ValueError:
        seed_obj = {}
    seed_version = int(seed_obj.get("seed_version", 1))

    if not row or not row["data"]:
        conn.execute("INSERT OR REPLACE INTO site_data (id, data) VALUES (1, ?)", (seed,))
        conn.commit()
        conn.close()
        return

    try:
        current = json.loads(row["data"])
    except ValueError:
        current = {}
    if int(current.get("seed_version", 0)) < seed_version:
        preserved = {
            k: current[k]
            for k in ("admin_users", "users", "admin_account")
            if k in current
        }
        current.update(seed_obj)
        current.update(preserved)
        conn.execute(
            "INSERT OR REPLACE INTO site_data (id, data) VALUES (1, ?)",
            (json.dumps(current),),
        )
        conn.commit()
    conn.close()


ensure_db()

def allowed_file(filename: str) -> bool:
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def is_safe_image(stream) -> bool:
    """Sniff magic bytes; SVG is rejected (can carry JS) even though it is text."""
    header = stream.read(512)
    stream.seek(0)
    kind = filetype.guess(header)
    if kind is None:
        return False
    return kind.extension in ALLOWED_EXTENSIONS


def load_data() -> Dict[str, Any]:
    defaults = default_site_data()
    try:
        conn = get_db_connection()
        row = conn.execute('SELECT data FROM site_data WHERE id = 1').fetchone()
        conn.close()
        if row and row['data']:
            data = json.loads(row['data'])
        else:
            data = {}
    except (sqlite3.Error, json.JSONDecodeError):
        data = {}

    if isinstance(data, dict):
        defaults.update(data)
    gallery = defaults.get("gallery", [])
    if "about_image" not in data:
        defaults["about_image"] = gallery[0] if len(gallery) > 0 else ""
    if "mission_image" not in data:
        defaults["mission_image"] = gallery[1] if len(gallery) > 1 else ""
    for index, item in enumerate(defaults.get("services", [])):
        if "image" not in item and len(gallery) > index + 2:
            item["image"] = gallery[index + 2]
    for index, item in enumerate(defaults.get("projects", [])):
        if "image" not in item and len(gallery) > index + 3:
            item["image"] = gallery[index + 3]
    return defaults


def save_data(data: Dict[str, Any]) -> None:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM site_data')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO site_data (data) VALUES (?)', (json.dumps(data),))
    else:
        c.execute('UPDATE site_data SET data = ? WHERE id = 1', (json.dumps(data),))
    conn.commit()
    conn.close()


def default_site_data() -> Dict[str, Any]:
    return {
        "site_name": "Initiative for Legal Aid South Sudan",
        "tagline": "Empowering Access To Justice In South Sudan",
        "hero_eyebrow": "Legal support for communities in need",
        "hero_meta": ["Trusted legal guidance", "Community-first advocacy"],
        "hero_image": "/static/uploads/hero.jpg",
        "about_image": "/static/uploads/gallery-1.jpg",
        "mission_image": "/static/uploads/gallery-2.jpg",
        "photo_titles": {
            "hero": "Hero image",
            "about": "About section photo",
            "mission": "Mission section photo"
        },
        "cta_text": "Get Legal Aid",
        "stats": [
            {"value": "24/7", "label": "Legal guidance support"},
            {"value": "3+", "label": "Core community programs"},
            {"value": "100%", "label": "Committed to justice access"}
        ],
        "about_title": "About Us",
        "about_story": "The Initiative for Legal Aid was established to ensure that justice is accessible to all South Sudanese citizens, aligning legal aid with the empowerment of communities.",
        "values": [
            {"title": "Justice And Equality", "text": "We believe in equal rights and opportunities for all."},
            {"title": "Integrity", "text": "We act with honesty, transparency, and accountability."},
            {"title": "Service", "text": "We stand with vulnerable communities and respond with dignity."}
        ],
        "mission": "We work to protect rights, promote legal awareness, and support vulnerable people through justice-focused advocacy and practical legal assistance.",
        "mission_eyebrow": "Why We Exist",
        "mission_title": "Justice should be within reach for every person.",
        "mission_text": "We work with vulnerable communities to improve access to legal information, practical support, and rights-based advocacy that promotes dignity, safety, and long-term resilience.",
        "mission_cards": [
            {"title": "Legal Awareness", "text": "Helping people understand their rights and the legal tools available to them."},
            {"title": "Advocacy", "text": "Championing the voices of those often left out of formal justice systems."},
            {"title": "Community Support", "text": "Building stronger local responses through dialogue, mediation, and outreach."}
        ],
        "services_eyebrow": "Our Services",
        "services_title": "What We Do",
        "services": [
            {"title": "Access To Justice", "text": "We provide free and subsidized legal assistance, ensuring vulnerable populations have the support they need to assert their rights and seek justice.", "image": "/static/uploads/gallery-3.jpg"},
            {"title": "Human Rights Protection", "text": "Our program focuses on monitoring, documenting, and advocating for victims of human rights violations while promoting respect for civil liberties.", "image": "/static/uploads/gallery-4.jpg"},
            {"title": "Women And Children\'s Rights", "text": "We champion gender equality and protection for women and children, offering legal support and advocacy against gender-based violence and discrimination.", "image": "/static/uploads/gallery-5.jpg"},
            {"title": "Peacebuilding", "text": "Our peacebuilding initiatives foster social cohesion, conflict resolution, and peaceful coexistence among communities affected by violence and displacement.", "image": "/static/uploads/gallery-6.jpg"}
        ],
        "projects": [
            {"title": "Legal Empowerment Workshops", "text": "These workshops equip individuals with essential legal knowledge to advocate effectively for their rights.", "image": "/static/uploads/gallery-4.jpg"},
            {"title": "Community Dialogues", "text": "Facilitated discussions that aim to resolve conflicts peacefully and strengthen community bonds.", "image": "/static/uploads/gallery-5.jpg"},
            {"title": "Advocacy Campaigns", "text": "Targeted campaigns raising awareness about human rights issues affecting local communities.", "image": "/static/uploads/gallery-6.jpg"}
        ],
        "projects_eyebrow": "Our Projects",
        "projects_title": "Initiatives That Make a Difference",
        "testimonials": [
            {"quote": "The support from ILA has changed my life. I finally received the help I needed to claim my rights.", "name": "Amina L.", "role": "Beneficiary", "image": "/static/uploads/testimonial-2.jpg"},
            {"quote": "ILA's advocacy work creates real change. We are grateful for their dedication to protecting our rights.", "name": "John D.", "role": "Human Rights Advocate", "image": "/static/uploads/testimonial-3.jpg"},
            {"quote": "Through ILA, we learned our rights as women. This knowledge empowers us to stand up and make a difference in our community.", "name": "Sarah M.", "role": "Community Leader", "image": "/static/uploads/testimonial-1.jpg"}
        ],
        "testimonials_eyebrow": "Testimonials",
        "testimonials_title": "What People Say",
        "contact_address": "Customs Business Area, Along Main Highway, Opp Dr. John Garang Mausoleum, Juba, Central Equatoria State, Republic of South Sudan",
        "contact_phone": "+211 922 460 564 / +211 920 800 802",
        "contact_email": "contact@domain.com",
        "gallery": [
            "/static/uploads/gallery-1.jpg",
            "/static/uploads/gallery-2.jpg",
            "/static/uploads/gallery-3.jpg",
            "/static/uploads/gallery-4.jpg",
            "/static/uploads/gallery-5.jpg",
            "/static/uploads/gallery-6.jpg"
        ],
        "gallery_eyebrow": "Gallery",
        "gallery_title": "Community Impact",
        "cta_eyebrow": "Need help?",
        "cta_title": "Speak with our team today.",
        "custom_sections": [],
        "pages": [],
        "admin_account": {},
        "admin_users": [],
        "users": []
    }


def parse_entries(value: str) -> List[Dict[str, str]]:
    entries = []
    for line in value.splitlines():
        if "|" in line:
            title, text = [part.strip() for part in line.split("|", 1)]
            if title and text:
                entries.append({"title": title, "text": text})
    return entries


def find_account(site: Dict[str, Any], identifier: str):
    """Look up an account by username or email across admins and users.
    Returns (account_dict, role) where role is 'admin' or 'user', or (None, None)."""
    ident = (identifier or "").strip().lower()
    if not ident:
        return None, None
    for admin in admin_users(site):
        if admin.get("username", "").lower() == ident:
            return admin, "admin"
    for user in site.get("users", []):
        if user.get("username", "").lower() == ident or user.get("email", "").lower() == ident:
            return user, "user"
    return None, None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "admin":
            flash("You need to log in to manage the site.")
            return redirect(url_for("unified_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def user_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_logged_in") or session.get("role") != "user":
            flash("Please log in to view your account.")
            return redirect(url_for("unified_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_account(data: Dict[str, Any]) -> Dict[str, str]:
    # Legacy single-admin shape; env is NOT used here. Empty hash = unusable until
    # an admin is created via ADMIN_BOOTSTRAP=1 or the dashboard's "Add admin user".
    account = data.get("admin_account") or {}
    return {
        "username": account.get("username", ""),
        "password_hash": account.get("password_hash", "")
    }


def admin_users(data: Dict[str, Any]) -> List[Dict[str, str]]:
    users = data.get("admin_users")
    if isinstance(users, list) and users:
        return users
    # Bootstrap from env ONLY when explicitly enabled (first deploy / recovery).
    # Env never overrides stored admins; set ADMIN_BOOTSTRAP=0 afterwards.
    if ADMIN_BOOTSTRAP_ENABLED and ADMIN_USERNAME and ADMIN_PASSWORD:
        users = [{"username": ADMIN_USERNAME,
                  "password_hash": generate_password_hash(ADMIN_PASSWORD, method="pbkdf2:sha256"),
                  "role": "admin"}]
        data["admin_users"] = users
        return users
    legacy = admin_account(data)
    if legacy.get("username") and legacy.get("password_hash"):
        users = [{"username": legacy["username"], "password_hash": legacy["password_hash"], "role": "admin"}]
        data["admin_users"] = users
        return users
    data["admin_users"] = []
    return data["admin_users"]


def handle_upload(file, fallback_name: str) -> str:
    if not file or file.filename == "":
        return fallback_name

    if not allowed_file(file.filename):
        flash("Invalid file extension. Only images are allowed.")
        return fallback_name
        
    if not is_safe_image(file.stream):
        flash("Invalid file content. The file does not appear to be a valid image.")
        return fallback_name

    filename = secure_filename(file.filename)
    # Append a unique identifier if file already exists to prevent overwriting
    base, ext = os.path.splitext(filename)
    counter = 1
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    while os.path.exists(file_path):
        filename = f"{base}_{counter}{ext}"
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        counter += 1

    file.save(file_path)
    return f"/static/uploads/{filename}"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "page"


def unique_slug(data: Dict[str, Any], title: str, current: str = "") -> str:
    base = slugify(title)
    candidate = base
    used = {page.get("slug") for page in data.get("pages", []) if page.get("slug") != current}
    counter = 2
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def photo_slots(site: Dict[str, Any]) -> List[Dict[str, str]]:
    titles = site.get("photo_titles", {})
    slots = [
        {"key": "hero", "label": "Hero image", "title": titles.get("hero", "Hero image"), "image": site.get("hero_image", "")},
        {"key": "about", "label": "About section", "title": titles.get("about", "About section photo"), "image": site.get("about_image", "")},
        {"key": "mission", "label": "Mission section", "title": titles.get("mission", "Mission section photo"), "image": site.get("mission_image", "")}
    ]
    slots.extend({"key": f"service-{index}", "label": f"Service {index + 1}", "title": item.get("title", ""), "image": item.get("image", "")} for index, item in enumerate(site.get("services", [])))
    slots.extend({"key": f"project-{index}", "label": f"Project {index + 1}", "title": item.get("title", ""), "image": item.get("image", "")} for index, item in enumerate(site.get("projects", [])))
    slots.extend({"key": f"testimonial-{index}", "label": f"Testimonial {index + 1}", "title": item.get("name", ""), "image": item.get("image", "")} for index, item in enumerate(site.get("testimonials", [])))
    slots.extend({"key": f"gallery-{index}", "label": f"Gallery image {index + 1}", "title": titles.get(f"gallery-{index}", f"Gallery image {index + 1}"), "image": image} for index, image in enumerate(site.get("gallery", [])))
    slots.extend({"key": f"custom-section-{index}", "label": f"Custom section {index + 1}", "title": item.get("title", ""), "image": item.get("image", "")} for index, item in enumerate(site.get("custom_sections", [])))
    slots.extend({"key": f"page-{index}", "label": f"Page {index + 1}", "title": item.get("title", ""), "image": item.get("image", "")} for index, item in enumerate(site.get("pages", [])))
    return slots


# Keys the database manager shows as view-only; they are edited from their own sections.
DB_PROTECTED_KEYS = frozenset({"admin_users", "users", "admin_account", "seed_version"})
GIT_PRIVATE_KEYS = frozenset({"admin_users", "users", "admin_account"})
GIT_CONTENT_COMMIT_LOCK = threading.Lock()
GIT_CONTENT_LOCK_FILE = os.path.join(tempfile.gettempdir(), "ila-admin-git-content.lock")


def _git_content_settings():
    """Return opt-in Git publishing settings, with safe production defaults."""
    config_value = os.environ.get("GIT_CONTENT_COMMIT", "").strip().lower()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    return {
        "enabled": config_value in {"1", "true", "yes", "on"} and bool(token),
        "branch": os.environ.get("GIT_CONTENT_BRANCH", "main").strip() or "main",
        "remote": os.environ.get("GIT_CONTENT_REMOTE", "origin").strip() or "origin",
        "token": token,
        "email": os.environ.get("GIT_CONTENT_EMAIL", "website@initiative4legalaid.org").strip(),
    }


def _changed_upload_paths(current: Dict[str, Any], previous: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Return upload paths referenced by changed content, validated under static/uploads."""
    def values(value: Any) -> List[str]:
        result: List[str] = []
        if isinstance(value, str):
            if value.startswith("/static/uploads/"):
                result.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                result.extend(values(item))
        elif isinstance(value, list):
            for item in value:
                result.extend(values(item))
        return result

    before = set(values(previous))
    after = set(values(current))
    added = sorted(after - before)
    removed = sorted(before - after)
    return added, removed


def _git_content_diff(site: Dict[str, Any], previous: Dict[str, Any]) -> str:
    labels = {
        "hero": "homepage hero", "contact": "contact details", "services": "services",
        "projects": "projects", "testimonials": "testimonials", "gallery": "gallery",
        "leadership": "leadership", "partnerships": "partnerships", "pages": "custom pages",
        "custom_sections": "custom sections", "impact": "impact information",
        "accountability": "accountability information", "knowledge": "knowledge centre"
    }
    changed = [labels.get(key, key.replace("_", " ")) for key in site if site.get(key) != previous.get(key)]
    return ", ".join(changed[:4]) or (", ".join(changed) if changed else "public site content")


def git_content_commit(site: Dict[str, Any], actor: str = "admin") -> Optional[str]:
    """Export public content and new public uploads, then commit/push when enabled."""
    settings = _git_content_settings()
    if not settings["enabled"]:
        return None
    repo_dir = os.path.dirname(SEED_FILE)
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        return "Content saved, but Git publishing is unavailable because the server repository is missing."

    previous: Dict[str, Any] = {}
    try:
        with open(SEED_FILE, "r", encoding="utf-8") as handle:
            previous = json.load(handle)
    except (OSError, ValueError):
        pass

    # seed_version is safe and necessary in the tracked seed. Credentials and
    # member accounts are never exported.
    safe_site = {key: value for key, value in site.items() if key not in GIT_PRIVATE_KEYS}
    added_uploads, _ = _changed_upload_paths(safe_site, previous)
    upload_repo_paths: List[str] = []
    upload_root = os.path.realpath(app.static_folder + "/uploads")
    for url_path in added_uploads:
        filename = os.path.basename(url_path)
        absolute = os.path.realpath(os.path.join(upload_root, filename))
        if os.path.commonpath([upload_root, absolute]) != upload_root or not os.path.isfile(absolute):
            continue
        upload_repo_paths.append("static/uploads/" + filename)

    actor = re.sub(r"[\r\n]+", " ", actor or "admin").strip()[:80] or "admin"
    commit_message = f"Content: update {_git_content_diff(safe_site, previous)}"
    tracked_paths = [os.path.basename(SEED_FILE), *upload_repo_paths]

    # Serialize within and across Gunicorn workers. SQLite has already been
    # updated before this function is called, so Git failures never lose an edit.
    with GIT_CONTENT_COMMIT_LOCK, open(GIT_CONTENT_LOCK_FILE, "a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            temp_seed = SEED_FILE + ".admin.tmp"
            with open(temp_seed, "w", encoding="utf-8") as handle:
                json.dump(safe_site, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_seed, SEED_FILE)

            def run_git(*args: str) -> subprocess.CompletedProcess:
                return subprocess.run(
                    ["git", *args], cwd=repo_dir, text=True, capture_output=True,
                    timeout=30, check=False,
                )

            if run_git("add", "-f", "--", *tracked_paths).returncode != 0:
                raise RuntimeError("could not stage the public content export")
            staged = run_git("diff", "--cached", "--quiet", "--", *tracked_paths)
            if staged.returncode not in (0, 1):
                raise RuntimeError("could not inspect the public content export")

            if staged.returncode == 1:
                committed = run_git(
                    "-c", f"user.name=ILA Admin ({actor})",
                    "-c", f"user.email={settings['email']}",
                    "commit", "--only", *tracked_paths, "-m", commit_message,
                )
                if committed.returncode != 0:
                    detail = (committed.stderr or committed.stdout or "Git commit failed").strip()
                    raise RuntimeError(detail[-300:])
            commit_hash = run_git("rev-parse", "--short", "HEAD").stdout.strip()

            push_env = os.environ.copy()
            if settings["token"]:
                # Keep the token out of command arguments and .git/config.
                push_env["GIT_CONFIG_COUNT"] = "1"
                push_env["GIT_CONFIG_KEY_0"] = "http.extraheader"
                push_env["GIT_CONFIG_VALUE_0"] = "Authorization: Bearer " + settings["token"]
            pushed = subprocess.run(
                ["git", "push", "--porcelain", settings["remote"], f"HEAD:{settings['branch']}"],
                cwd=repo_dir, env=push_env, text=True, capture_output=True,
                timeout=45, check=False,
            )
            if pushed.returncode != 0:
                detail = (pushed.stderr or pushed.stdout or "Git push failed").strip()
                raise RuntimeError("content was committed locally, but not pushed: " + detail[-300:])
            return f"Content saved and published in Git commit {commit_hash}."
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return "Content saved, but Git publishing needs attention: " + str(exc)[:300]
        finally:
            try:
                os.unlink(SEED_FILE + ".admin.tmp")
            except OSError:
                pass


def publish_admin_content(data: Dict[str, Any], actor: str = "admin") -> Optional[str]:
    """Persist a public admin edit, bump its seed version, then publish to Git."""
    data["seed_version"] = int(data.get("seed_version", 0) or 0) + 1
    save_data(data)
    result = git_content_commit(data, actor)
    if result:
        flash(result)
    return result




# Sentinel for "key not present" (so a real null value is still editable).
_MISSING = object()


def db_key_rows(site):
    """One summary row per top-level data key for the database manager."""
    rows = []
    for key in sorted(site.keys()):
        value = site[key]
        try:
            size_kb = round(len(json.dumps(value, ensure_ascii=False).encode("utf-8")) / 1024, 1)
        except (TypeError, ValueError):
            size_kb = 0.0
        if isinstance(value, list):
            kind, count = "list", len(value)
        elif isinstance(value, dict):
            kind, count = "object", len(value)
        elif isinstance(value, str):
            kind, count = "text", len(value)
        else:
            kind, count = type(value).__name__, "-"
        rows.append({
            "key": key,
            "kind": kind,
            "count": count,
            "size_kb": size_kb,
            "protected": key in DB_PROTECTED_KEYS,
        })
    return rows


# ===== Contact messages: website enquiry inbox + email notification =====
def mail_configured() -> bool:
    """True when every value needed to send a notification email is present."""
    return bool(MAIL_API_KEY and MAIL_FROM and MAIL_TO)


def save_message(name: str, email: str, phone: str, subject: str, body: str, ip: str) -> int:
    conn = get_db_connection()
    cursor = conn.execute(
        """INSERT INTO contact_messages (created_at, name, email, phone, subject, body, ip)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name, email, phone, subject, body, ip),
    )
    message_id = int(cursor.lastrowid or 0)
    conn.commit()
    conn.close()
    return message_id


def recent_message_count(ip: str, hours: int = 1) -> int:
    """Submissions from one IP in the last `hours` — a light spam brake."""
    if not ip:
        return 0
    conn = get_db_connection()
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        "SELECT COUNT(*) FROM contact_messages WHERE ip = ? AND created_at >= ?", (ip, since)
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def list_messages() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM contact_messages ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def unread_message_count() -> int:
    conn = get_db_connection()
    row = conn.execute("SELECT COUNT(*) FROM contact_messages WHERE is_read = 0").fetchone()
    conn.close()
    return int(row[0]) if row else 0


def set_message_status(message_id: int, is_read: int = None, mail_status: str = None) -> None:
    fields, params = [], []
    if is_read is not None:
        fields.append("is_read = ?")
        params.append(is_read)
    if mail_status is not None:
        fields.append("mail_status = ?")
        params.append(mail_status)
    if not fields:
        return
    params.append(message_id)
    conn = get_db_connection()
    conn.execute("UPDATE contact_messages SET %s WHERE id = ?" % ", ".join(fields), params)
    conn.commit()
    conn.close()


def delete_message(message_id: int) -> None:
    conn = get_db_connection()
    conn.execute("DELETE FROM contact_messages WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()


def send_notification_email(subject: str, body: str, reply_to: str = "") -> str:
    """Send one notification over an HTTPS mail API (works on Render).

    Returns a short status string stored alongside the message so the admin
    inbox always shows whether the email actually went out.
    """
    if not mail_configured():
        return "not_configured"
    payload = {
        "from": MAIL_FROM,
        "to": [address.strip() for address in MAIL_TO.split(",") if address.strip()],
        "subject": subject,
        "text": body,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    request_object = urllib.request.Request(
        MAIL_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer %s" % MAIL_API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_object, timeout=10) as response:
            if 200 <= response.status < 300:
                return "sent"
            return "failed: HTTP %s" % response.status
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read(200).decode("utf-8", "replace")
        except Exception:
            detail = ""
        return "failed: HTTP %s %s" % (error.code, detail.strip())
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return "failed: %s" % error


@app.route("/admin/database", methods=["GET"])
@login_required
def admin_database():
    site = load_data()
    edit_key = (request.args.get("edit") or "").strip()
    rows = db_key_rows(site)
    edit_value = ""
    if edit_key:
        value = site.get(edit_key, _MISSING)
        if value is _MISSING:
            flash("Key '%s' does not exist." % edit_key)
            return redirect(url_for("admin_database"))
        if edit_key in DB_PROTECTED_KEYS:
            flash("Key '%s' is protected and managed from its own section." % edit_key)
            return redirect(url_for("admin_database"))
        edit_value = json.dumps(value, indent=2, ensure_ascii=False)
    return render_template(
        "admin_database.html",
        site=site,
        db_rows=rows,
        db_total_kb=round(len(json.dumps(site, ensure_ascii=False).encode("utf-8")) / 1024, 1),
        edit_key=edit_key or None,
        edit_value=edit_value,
    )


@app.route("/admin/database/update", methods=["POST"])
@login_required
def admin_database_update():
    site = load_data()
    key = (request.form.get("key") or "").strip()
    raw = request.form.get("value", "")
    if not key or key not in site:
        flash("Unknown key — nothing was saved.")
        return redirect(url_for("admin_database"))
    if key in DB_PROTECTED_KEYS:
        flash("Key '%s' is protected and cannot be edited here." % key)
        return redirect(url_for("admin_database"))
    try:
        site[key] = json.loads(raw)
    except ValueError as exc:
        flash("Invalid JSON — nothing was saved. Error: %s" % exc)
        return redirect(url_for("admin_database", edit=key))
    publish_admin_content(site, session.get("username", "admin"))
    flash("Key '%s' has been updated." % key)
    return redirect(url_for("admin_database", edit=key))


@app.route("/admin/database/add", methods=["POST"])
@login_required
def admin_database_add():
    site = load_data()
    key = (request.form.get("key") or "").strip()
    raw = request.form.get("value", "[]")
    if not key:
        flash("Give the new key a name.")
        return redirect(url_for("admin_database"))
    if key in site or key in DB_PROTECTED_KEYS:
        flash("Key '%s' already exists or is reserved." % key)
        return redirect(url_for("admin_database"))
    try:
        site[key] = json.loads(raw)
    except ValueError as exc:
        flash("Invalid JSON for the new key: %s" % exc)
        return redirect(url_for("admin_database"))
    publish_admin_content(site, session.get("username", "admin"))
    flash("Key '%s' has been added." % key)
    return redirect(url_for("admin_database", edit=key))


@app.route("/admin/database/delete", methods=["POST"])
@login_required
def admin_database_delete():
    site = load_data()
    key = (request.form.get("key") or "").strip()
    if not key or key not in site:
        flash("Unknown key — nothing was deleted.")
    elif key in DB_PROTECTED_KEYS:
        flash("Key '%s' is protected and cannot be deleted." % key)
    else:
        del site[key]
        publish_admin_content(site, session.get("username", "admin"))
        flash("Key '%s' has been deleted." % key)
    return redirect(url_for("admin_database"))


@app.route("/admin/database/export", methods=["GET"])
@login_required
def admin_database_export():
    site = load_data()
    export = {k: v for k, v in site.items() if k not in DB_PROTECTED_KEYS}
    payload = json.dumps(export, indent=2, ensure_ascii=False)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=ila-site-content-%s.json" % datetime.now().strftime("%Y%m%d")},
    )


@app.route("/admin/database/import", methods=["POST"])
@login_required
def admin_database_import():
    site = load_data()
    upload = request.files.get("import_file")
    if not upload or not upload.filename:
        flash("Choose a JSON file to import.")
        return redirect(url_for("admin_database"))
    try:
        imported = json.loads(upload.stream.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        flash("That file is not valid JSON: %s" % exc)
        return redirect(url_for("admin_database"))
    if not isinstance(imported, dict):
        flash("The import file must contain a JSON object of keys.")
        return redirect(url_for("admin_database"))
    applied = 0
    for key, value in imported.items():
        if key in DB_PROTECTED_KEYS:
            continue
        site[key] = value
        applied += 1
    publish_admin_content(site, session.get("username", "admin"))
    flash("Import complete: %d keys applied. Accounts were preserved." % applied)
    return redirect(url_for("admin_database"))


@app.route("/admin/database/reset", methods=["POST"])
@login_required
def admin_database_reset():
    site = load_data()
    kept = {k: site[k] for k in DB_PROTECTED_KEYS if k in site}
    try:
        with open(SEED_FILE, "r", encoding="utf-8") as f:
            seed_obj = json.load(f)
    except (OSError, ValueError) as exc:
        flash("Could not load the shipped defaults: %s" % exc)
        return redirect(url_for("admin_database"))
    seed_obj.update(kept)
    publish_admin_content(seed_obj, session.get("username", "admin"))
    flash("All content has been reset to the shipped defaults. Accounts were preserved.")
    return redirect(url_for("admin_database"))


def set_photo(data: Dict[str, Any], target: str, image: str) -> bool:
    if target == "hero":
        data["hero_image"] = image
    elif target == "about":
        data["about_image"] = image
    elif target == "mission":
        data["mission_image"] = image
    else:
        try:
            group, raw_index = target.rsplit("-", 1)
            index = int(raw_index)
            if group == "service":
                data["services"][index]["image"] = image
            elif group == "project":
                data["projects"][index]["image"] = image
            elif group == "testimonial":
                data["testimonials"][index]["image"] = image
            elif group == "gallery":
                data["gallery"][index] = image
            elif group == "custom-section":
                data["custom_sections"][index]["image"] = image
            elif group == "page":
                data["pages"][index]["image"] = image
            else:
                return False
        except (ValueError, IndexError, KeyError):
            return False
    return True


def set_photo_title(data: Dict[str, Any], target: str, title: str) -> bool:
    if target in ("hero", "about", "mission") or target.startswith("gallery-"):
        data.setdefault("photo_titles", {})[target] = title
        return True
    try:
        group, raw_index = target.rsplit("-", 1)
        index = int(raw_index)
        if group == "service":
            data["services"][index]["title"] = title
        elif group == "project":
            data["projects"][index]["title"] = title
        elif group == "testimonial":
            data["testimonials"][index]["name"] = title
        elif group == "custom-section":
            data["custom_sections"][index]["title"] = title
        elif group == "page":
            data["pages"][index]["title"] = title
        else:
            return False
    except (ValueError, IndexError, KeyError):
        return False
    return True


@app.route("/admin/messages")
@login_required
def admin_messages():
    """Inbox for enquiries submitted through the public contact form."""
    site = load_data()
    return render_template(
        "admin_messages.html",
        site=site,
        messages=list_messages(),
        unread_messages=unread_message_count(),
        mail_ready=mail_configured(),
        mail_to=MAIL_TO,
        mail_from=MAIL_FROM,
    )


@app.route("/admin/messages/<int:message_id>/read", methods=["POST"])
@login_required
def admin_message_read(message_id: int):
    set_message_status(message_id, is_read=1)
    flash("Message marked as read.")
    return redirect(url_for("admin_messages"))


@app.route("/admin/messages/<int:message_id>/unread", methods=["POST"])
@login_required
def admin_message_unread(message_id: int):
    set_message_status(message_id, is_read=0)
    flash("Message marked as unread.")
    return redirect(url_for("admin_messages"))


@app.route("/admin/messages/<int:message_id>/delete", methods=["POST"])
@login_required
def admin_message_delete(message_id: int):
    delete_message(message_id)
    flash("Message deleted.")
    return redirect(url_for("admin_messages"))


@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html", site=load_data()), 404


@app.errorhandler(413)
def request_too_large(error):
    flash("That file is too large. Images must be under 16 MB.")
    redirect_to = request.referrer or url_for("index")
    return redirect(redirect_to), 413


@app.route("/")
def index():
    site = load_data()
    return render_template("index.html", site=site)


@app.route("/page/<slug>")
def custom_page(slug: str):
    site = load_data()
    page = next((item for item in site.get("pages", []) if item.get("slug") == slug), None)
    if not page:
        return render_template("404.html", site=site), 404
    return render_template("page.html", site=site, page=page)


@app.route("/profile")
def profile():
    site = load_data()
    return render_template("profile.html", site=site)


@app.route("/partnerships")
def partnerships():
    site = load_data()
    return render_template("partnerships.html", site=site)


@app.route("/leadership")
def leadership():
    site = load_data()
    return render_template("leadership.html", site=site)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    """Public enquiry form.

    Every submission is saved to the database first, so an enquiry is never
    lost even when email delivery is not configured or the provider is down.
    """
    site = load_data()
    form = {"name": "", "email": "", "phone": "", "subject": "", "message": ""}
    if request.method == "POST":
        form = {
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "subject": request.form.get("subject", "").strip(),
            "message": request.form.get("message", "").strip(),
        }
        forwarding = request.headers.get("X-Forwarded-For", "") or request.remote_addr or ""
        ip = forwarding.split(",")[0].strip()
        subject = form["subject"] or "Website enquiry"

        if request.form.get("website", "").strip():
            # Honeypot field filled in: treat as a bot, but respond normally.
            flash("Thank you. Your message has been received.")
            return redirect(url_for("contact"))
        if not form["name"] or not form["message"]:
            flash("Please provide your name and a message.")
        elif "@" not in form["email"] or "." not in form["email"].rsplit("@", 1)[-1]:
            flash("Please provide a valid email address so the team can reply.")
        elif recent_message_count(ip) >= CONTACT_RATE_LIMIT:
            flash("You have already sent several messages. Please try again later, or call the office.")
        else:
            message_id = save_message(
                form["name"], form["email"], form["phone"], subject, form["message"], ip
            )
            body = (
                "New website enquiry — %s\n\n"
                "Name:  %s\n"
                "Email: %s\n"
                "Phone: %s\n"
                "Subject: %s\n\n"
                "Message:\n%s\n\n"
                "--\n"
                "Sent from the contact form at %s\n"
                "Reference: #%s\n"
            ) % (
                site.get("site_name", "ILA"),
                form["name"],
                form["email"],
                form["phone"] or "—",
                subject,
                form["message"],
                request.url_root.rstrip("/"),
                message_id,
            )
            try:
                status = send_notification_email(subject, body, reply_to=form["email"])
            except Exception as error:  # never lose a submission because mail failed
                status = "failed: %s" % error
            set_message_status(message_id, mail_status=status)
            if status == "sent":
                flash("Thank you. Your message has been sent — our team will reply shortly.")
            else:
                flash("Thank you. Your message has been received and added to the office inbox.")
            return redirect(url_for("contact"))
    return render_template("contact.html", site=site, form=form, mail_ready=mail_configured())


@app.route("/login", methods=["GET", "POST"])
def unified_login():
    """Single shared login page (same theme) for admins and regular users.
    Role is detected automatically; each role is redirected to its own area.
    NOTE: one browser holds ONE role at a time — logging in as the other role
    clears the first session (intentional, prevents privilege confusion)."""
    site = load_data()
    # Already logged in? Send each role to its home.
    if session.get("logged_in") and session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    if session.get("user_logged_in") and session.get("role") == "user":
        return redirect(url_for("user_account"))
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember")
        account, role = find_account(site, identifier)
        if account and check_password_hash(account.get("password_hash", ""), password):
            # Single-role session: clear first so admin/user logins never mix in one browser.
            session.clear()
            if remember:
                session.permanent = True  # 30-day cookie: stay logged in across restarts
            else:
                session.permanent = False  # browser-session cookie: logged out on browser close
            if role == "admin":
                session["logged_in"] = True
                session["username"] = account["username"]
                session["role"] = "admin"
                flash("Login successful. Welcome back, admin.")
                requested = request.args.get("next") or request.form.get("next")
                if requested and requested.startswith("/admin"):
                    return redirect(requested)
                return redirect(url_for("admin_dashboard"))
            session["user_logged_in"] = True
            session["user_username"] = account["username"]
            session["role"] = "user"
            flash("Welcome back.")
            requested = request.args.get("next") or request.form.get("next")
            if requested and requested.startswith("/") and not requested.startswith("/admin"):
                return redirect(requested)
            return redirect(url_for("user_account"))
        flash("Invalid login details.")
    return render_template("login.html", site=site)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    # Keep old URL working: same theme, same logic as unified login.
    if request.method == "POST":
        return unified_login()
    site = load_data()
    if session.get("logged_in") and session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    return render_template("login.html", site=site, login_title="Admin Login",
                           login_subtitle="Manage the Initiative for Legal Aid website.")


@app.route("/register", methods=["GET", "POST"])
def register():
    site = load_data()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        users = site.setdefault("users", [])
        if not username or not email or not password:
            flash("Username, email, and password are required.")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.")
        elif password != confirm_password:
            flash("Passwords do not match.")
        elif any(user.get("username", "").lower() == username.lower() for user in users):
            flash("That username is already registered.")
        elif any(admin.get("username", "").lower() == username.lower() for admin in admin_users(site)):
            flash("That username is reserved for an administrator.")
        elif any(user.get("email", "").lower() == email for user in users):
            flash("That email is already registered.")
        else:
            users.append({"username": username, "email": email, "password_hash": generate_password_hash(password, method="pbkdf2:sha256"), "role": "user"})
            save_data(site)
            session.clear()
            session.permanent = True  # stay logged in after registering (30-day cookie)
            session["user_logged_in"] = True
            session["user_username"] = username
            session["role"] = "user"
            flash("Your account has been created.")
            return redirect(url_for("user_account"))
    return render_template("register.html", site=site)


@app.route("/user/login", methods=["GET", "POST"])
def user_login():
    # Backwards-compatible alias for the old user login URL.
    if request.method == "POST":
        return unified_login()
    site = load_data()
    if session.get("user_logged_in") and session.get("role") == "user":
        return redirect(url_for("user_account"))
    return render_template("login.html", site=site)


@app.route("/logout")
def user_logout():
    session.pop("user_logged_in", None)
    session.pop("user_username", None)
    # Keep admin login intact if an admin is also logged in; only clear role if no login remains
    if not session.get("logged_in"):
        session.pop("role", None)
    flash("You have been logged out.")
    return redirect(url_for("index"))


@app.route("/account")
@user_required
def user_account():
    site = load_data()
    user = next((item for item in site.get("users", []) if item.get("username") == session.get("user_username")), None)
    if not user:
        return user_logout()
    return render_template("user_account.html", site=site, user=user)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    site = load_data()
    return render_template(
        "admin_dashboard.html",
        site=site,
        values=site["values"],
        photo_slots=photo_slots(site),
        admin_users=admin_users(site),
        unread_messages=unread_message_count()
    )


@app.route("/admin/account", methods=["POST"])
@login_required
def update_admin_account():
    data = load_data()
    users = admin_users(data)
    current_username = session.get("username", "")
    account = next((user for user in users if user.get("username") == current_username), None)
    if not account:
        session.clear()
        flash("Your admin account could not be found.")
        return redirect(url_for("admin_login"))
    current_password = request.form.get("current_password", "")
    username = request.form.get("username", "").strip()
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not check_password_hash(account["password_hash"], current_password):
        flash("Current password is incorrect.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    if not username:
        flash("Username cannot be empty.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    if any(user is not account and user.get("username") == username for user in users):
        flash("That username is already in use.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    if new_password and new_password != confirm_password:
        flash("The new passwords do not match.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    if new_password and len(new_password) < 8:
        flash("The new password must be at least 8 characters.")
        return redirect(url_for("admin_dashboard", _anchor="security"))

    account["username"] = username
    account["role"] = "admin"
    account["password_hash"] = generate_password_hash(new_password or current_password, method="pbkdf2:sha256")
    data["admin_users"] = users
    save_data(data)
    session.clear()
    flash("Admin credentials updated. Please log in again.")
    return redirect(url_for("admin_login"))


@app.route("/admin/users/create", methods=["POST"])
@login_required
def create_admin_user():
    data = load_data()
    users = admin_users(data)
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    if not username or not password:
        flash("Username and password are required.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    if len(password) < 8:
        flash("The new user's password must be at least 8 characters.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    if password != confirm_password:
        flash("The new user's passwords do not match.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    if any(user.get("username") == username for user in users):
        flash("That username already exists.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    users.append({"username": username, "password_hash": generate_password_hash(password, method="pbkdf2:sha256"), "role": "admin"})
    data["admin_users"] = users
    save_data(data)
    flash("Admin user added successfully.")
    return redirect(url_for("admin_dashboard", _anchor="security"))


@app.route("/admin/users/<username>/delete", methods=["POST"])
@login_required
def delete_admin_user(username: str):
    data = load_data()
    users = admin_users(data)
    if username == session.get("username"):
        flash("You cannot delete the account you are currently using.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    if len(users) <= 1:
        flash("At least one admin user must remain.")
        return redirect(url_for("admin_dashboard", _anchor="security"))
    remaining = [user for user in users if user.get("username") != username]
    if len(remaining) == len(users):
        flash("That admin user could not be found.")
    else:
        data["admin_users"] = remaining
        save_data(data)
        flash("Admin user deleted.")
    return redirect(url_for("admin_dashboard", _anchor="security"))


@app.route("/admin/custom-section/create", methods=["POST"])
@login_required
def create_custom_section():
    data = load_data()
    title = request.form.get("title", "").strip()
    text = request.form.get("text", "").strip()
    if not title or not text:
        flash("A section title and description are required.")
        return redirect(url_for("admin_dashboard", _anchor="custom-content"))
    image = handle_upload(request.files.get("image"), "")
    data.setdefault("custom_sections", []).append({"title": title, "text": text, "image": image})
    publish_admin_content(data, session.get("username", "admin"))
    flash("Custom photo section created.")
    return redirect(url_for("admin_dashboard", _anchor="custom-content"))


@app.route("/admin/custom-section/<int:index>/delete", methods=["POST"])
@login_required
def delete_custom_section(index: int):
    data = load_data()
    try:
        data.setdefault("custom_sections", []).pop(index)
    except IndexError:
        flash("That custom section could not be found.")
        return redirect(url_for("admin_dashboard", _anchor="custom-content"))
    publish_admin_content(data, session.get("username", "admin"))
    flash("Custom section deleted.")
    return redirect(url_for("admin_dashboard", _anchor="custom-content"))


@app.route("/admin/page/create", methods=["POST"])
@login_required
def create_page():
    data = load_data()
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    if not title or not content:
        flash("A page title and content are required.")
        return redirect(url_for("admin_dashboard", _anchor="custom-content"))
    image = handle_upload(request.files.get("image"), "")
    data.setdefault("pages", []).append({"title": title, "slug": unique_slug(data, title), "content": content, "image": image})
    publish_admin_content(data, session.get("username", "admin"))
    flash("Page created successfully.")
    return redirect(url_for("admin_dashboard", _anchor="custom-content"))


@app.route("/admin/page/<slug>/delete", methods=["POST"])
@login_required
def delete_page(slug: str):
    data = load_data()
    pages = data.setdefault("pages", [])
    data["pages"] = [page for page in pages if page.get("slug") != slug]
    publish_admin_content(data, session.get("username", "admin"))
    flash("Page deleted.")
    return redirect(url_for("admin_dashboard", _anchor="custom-content"))


@app.route("/admin/photo/<target>/update", methods=["POST"])
@login_required
def update_photo(target: str):
    data = load_data()
    uploaded = request.files.get("photo")
    title = request.form.get("title", "").strip()
    changed = False
    if title:
        changed = set_photo_title(data, target, title)
    if uploaded and uploaded.filename:
        image = handle_upload(uploaded, "")
        changed = set_photo(data, target, image) or changed
    if not changed:
        flash("Choose a photo or enter a title before saving.")
        return redirect(url_for("admin_dashboard", _anchor="media"))
    publish_admin_content(data, session.get("username", "admin"))
    flash("Photo details updated successfully.")
    return redirect(url_for("admin_dashboard", _anchor="media"))


@app.route("/admin/photo/<target>/delete", methods=["POST"])
@login_required
def delete_photo(target: str):
    data = load_data()
    if not set_photo(data, target, ""):
        flash("That photo slot could not be found.")
        return redirect(url_for("admin_dashboard", _anchor="media"))
    publish_admin_content(data, session.get("username", "admin"))
    flash("Photo removed successfully.")
    return redirect(url_for("admin_dashboard", _anchor="media"))


@app.route("/admin/update", methods=["POST"])
@login_required
def update_site():
    data = load_data()
    form = request.form

    data["site_name"] = form.get("site_name", data.get("site_name"))
    data["tagline"] = form.get("tagline", data.get("tagline"))
    data["hero_eyebrow"] = form.get("hero_eyebrow", data.get("hero_eyebrow"))
    data["hero_meta"] = [line.strip() for line in form.get("hero_meta", "").splitlines() if line.strip()] or data.get("hero_meta", [])
    data["cta_text"] = form.get("cta_text", data.get("cta_text"))
    data["about_title"] = form.get("about_title", data.get("about_title"))
    data["about_story"] = form.get("about_story", data.get("about_story"))
    data["mission"] = form.get("mission", data.get("mission"))
    data["mission_eyebrow"] = form.get("mission_eyebrow", data.get("mission_eyebrow"))
    data["mission_title"] = form.get("mission_title", data.get("mission_title"))
    data["mission_text"] = form.get("mission_text", data.get("mission_text"))
    data["services_eyebrow"] = form.get("services_eyebrow", data.get("services_eyebrow"))
    data["services_title"] = form.get("services_title", data.get("services_title"))
    data["projects_eyebrow"] = form.get("projects_eyebrow", data.get("projects_eyebrow"))
    data["projects_title"] = form.get("projects_title", data.get("projects_title"))
    data["testimonials_eyebrow"] = form.get("testimonials_eyebrow", data.get("testimonials_eyebrow"))
    data["testimonials_title"] = form.get("testimonials_title", data.get("testimonials_title"))
    data["gallery_eyebrow"] = form.get("gallery_eyebrow", data.get("gallery_eyebrow"))
    data["gallery_title"] = form.get("gallery_title", data.get("gallery_title"))
    data["cta_eyebrow"] = form.get("cta_eyebrow", data.get("cta_eyebrow"))
    data["cta_title"] = form.get("cta_title", data.get("cta_title"))
    data["contact_address"] = form.get("contact_address", data.get("contact_address"))
    data["contact_phone"] = form.get("contact_phone", data.get("contact_phone"))
    data["contact_email"] = form.get("contact_email", data.get("contact_email"))

    stats_text = form.get("stats_text", "")
    if stats_text.strip():
        data["stats"] = [{"value": entry["title"], "label": entry["text"]} for entry in parse_entries(stats_text)]

    values_text = form.get("values_text", "")
    if values_text.strip():
        data["values"] = parse_entries(values_text)

    mission_cards_text = form.get("mission_cards_text", "")
    if mission_cards_text.strip():
        data["mission_cards"] = parse_entries(mission_cards_text)

    services_text = form.get("services_text", "")
    if services_text.strip():
        data["services"] = parse_entries(services_text)

    projects_text = form.get("projects_text", "")
    if projects_text.strip():
        data["projects"] = parse_entries(projects_text)

    testimonials_text = form.get("testimonials_text", "")
    if testimonials_text.strip():
        existing_testimonials = data.get("testimonials", [])
        data["testimonials"] = []
        for index, line in enumerate(testimonials_text.splitlines()):
            if "|" in line:
                quote, author = [part.strip() for part in line.split("|", 1)]
                if quote and author:
                    name_part = author.split("-")
                    role = name_part[-1].strip() if len(name_part) > 1 else "Beneficiary"
                    name = author.replace("-" + role, "").strip()
                    testimonial = {"quote": quote, "name": name, "role": role}
                    if index < len(existing_testimonials) and existing_testimonials[index].get("image"):
                        testimonial["image"] = existing_testimonials[index]["image"]
                    data["testimonials"].append(testimonial)

    hero_image = request.files.get("hero_image")
    if hero_image and hero_image.filename:
        data["hero_image"] = handle_upload(hero_image, data.get("hero_image", "/static/uploads/hero.jpg"))

    gallery_images = request.files.getlist("gallery_images")
    if gallery_images:
        for gallery_file in gallery_images:
            if gallery_file and gallery_file.filename:
                image_path = handle_upload(gallery_file, "")
                if image_path:
                    data.setdefault("gallery", [])
                    data["gallery"].append(image_path)

    publish_admin_content(data, session.get("username", "admin"))
    flash("The website content has been updated successfully.")
    return redirect(url_for("admin_dashboard"))


def get_local_port() -> int:
    configured_port = os.environ.get("PORT")
    if configured_port:
        return int(configured_port)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("", 5000))
            return 5000
        except OSError:
            probe.bind(("", 0))
            return probe.getsockname()[1]


if __name__ == "__main__":
    port = get_local_port()
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port)
