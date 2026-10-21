#!/usr/bin/env python3
"""Mirror production admin-panel content locally — database-only sync.

Render's built-in publisher (GIT_CONTENT_COMMIT) needs a GITHUB_TOKEN secret on
Render that is not configured. Until it is, this script closes the loop from
here every 15 minutes (cron): it logs into the production admin panel, exports
public content, and merges it in two places:

1. site_data.json (tracked seed) — production wins; commit + push when changed.
2. Local site.db (gitignored, never committed) — three-way merge of the last
   synced export, the fresh production export, and the local database, with
   production winning every conflict; local-only additions are pushed back to
   production via the panel import (additive only, accounts never touched).

It also keeps dated content backups under backups/ (gitignored) so panel
content can be restored without a DB snapshot.

Credentials come from .env (gitignored): PROD_ADMIN_USER / PROD_ADMIN_PASSWORD,
falling back to ADMIN_USERNAME / ADMIN_PASSWORD. Stdlib only — no new deps.
Run via cron every 15 minutes; quiet when nothing changed.
"""
import http.cookiejar
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
SITE_URL = os.environ.get("PROD_SITE_URL", "https://initiative4legalaid.org").rstrip("/")
USER_AGENT = "ila-content-sync/1.0"
PRIVATE_KEYS = frozenset({"admin_users", "users", "admin_account", "seed_version"})
KEEP_BACKUPS = 30
LOG_FILE = Path.home() / "Library/Logs/ila-content-sync.log"
LOCAL_DB = REPO / "site.db"
SYNC_STATE = REPO / "backups" / ".last-prod-export.json"
_MISSING = object()


def read_local_db(path: Path = LOCAL_DB) -> dict:
    """Read the live JSON blob (id=1) from a site.db file; {} when missing."""
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except sqlite3.Error:
        return {}
    try:
        row = conn.execute("SELECT data FROM site_data WHERE id = 1").fetchone()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    if not row or not row[0]:
        return {}
    try:
        data = json.loads(row[0])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def write_local_db(data: dict, path: Path = LOCAL_DB) -> None:
    """Upsert the id=1 blob into a local site.db (gitignored, never committed).

    Uses a file backup first so a crashed write can be restored by hand.
    """
    backup = path.with_suffix(".db.pre-sync-bak")
    if path.exists():
        shutil.copy2(path, backup)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS site_data (id INTEGER PRIMARY KEY, data JSON)")
        conn.execute(
            "INSERT OR REPLACE INTO site_data (id, data) VALUES (1, ?)",
            (json.dumps(data, ensure_ascii=False),),
        )
        conn.commit()
    finally:
        conn.close()
    if backup.exists():
        backup.unlink()


def merge_local_db(export: dict, baseline: dict, db_path: Optional[Path] = None) -> tuple:
    """Three-way merge production export into the local DB; production wins.

    Compares the fresh production export against the last-synced baseline and
    the current local DB, then rewrites the local DB when the merge changes
    it. Private keys (accounts/seed_version) are always the local copy.
    Returns (changed: bool, pushed_up: list[str], skipped_push: list[str]).

    - A key changed on production since baseline: production value wins,
      even if the local DB also changed it (conflict -> production).
    - A key changed only locally: local value kept in the DB, and the key is
      reported back so the caller can push it up to production (additive).
    - A key deleted on production: removed locally only if untouched locally.
    """
    local = read_local_db(db_path or LOCAL_DB)
    merged = dict(local)
    touched, pushed_up, skipped_push = [], [], []

    for key, value in export.items():
        if key in PRIVATE_KEYS:
            merged[key] = local.get(key, value)
            continue
        if value != baseline.get(key, _MISSING):
            merged[key] = value  # new or changed on production -> wins
            if key != local.get(key, _MISSING):
                touched.append(key)
        elif key not in merged:
            merged[key] = value
            touched.append(key)

    for key in list(merged):
        if key in PRIVATE_KEYS or key in export:
            continue
        if key not in baseline:
            pushed_up.append(key)  # local-only addition -> push up
        elif merged[key] == baseline[key]:
            del merged[key]  # deleted on production, untouched locally
            touched.append(key)
        else:
            skipped_push.append(key)  # deleted on production but edited locally

    if merged.get("seed_version", 0) != export.get("seed_version", 0):
        if "seed_version" in export:
            merged["seed_version"] = export["seed_version"]
    changed = merged != local
    if changed:
        write_local_db(merged, db_path or LOCAL_DB)
    return changed, pushed_up, skipped_push


def log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")


def fail(message: str) -> int:
    log("ERROR: " + message)
    print("ERROR:", message)
    return 1


load_dotenv(REPO / ".env")
ADMIN_USER = (os.environ.get("PROD_ADMIN_USER") or os.environ.get("ADMIN_USERNAME") or "").strip()
ADMIN_PASS = (os.environ.get("PROD_ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD") or "").strip()
if not ADMIN_USER or not ADMIN_PASS:
    sys.exit(fail("no production admin credentials in .env (PROD_ADMIN_USER/PROD_ADMIN_PASSWORD)"))

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def fetch(path: str, timeout: int = 90) -> str:
    request = urllib.request.Request(SITE_URL + path, headers={"User-Agent": USER_AGENT})
    with opener.open(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def post_form(path: str, data: dict, referer: str, timeout: int = 90) -> str:
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        SITE_URL + path,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": referer,
        },
    )
    with opener.open(request, timeout=timeout) as response:
        return response.geturl()


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO, text=True, capture_output=True, timeout=60, check=False
    )


def post_multipart(path: str, fields: dict, files: dict, referer: str, timeout: int = 120) -> str:
    """POST a multipart/form-data body (for the panel import endpoint)."""
    boundary = "----ila-sync-%s" % datetime.now().strftime("%Y%m%d%H%M%S%f")
    chunks = []
    for name, value in fields.items():
        chunks.append(
            ("--" + boundary + '\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (name, value)).encode()
        )
    for name, (filename, content, mimetype) in files.items():
        chunks.append(
            (
                "--" + boundary + '\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
                % (name, filename, mimetype)
            ).encode() + content + b"\r\n"
        )
    chunks.append(("--" + boundary + "--\r\n").encode())
    body = b"".join(chunks)
    request = urllib.request.Request(
        SITE_URL + path,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "Referer": referer,
        },
    )
    with opener.open(request, timeout=timeout) as response:
        return response.geturl()


def main() -> int:
    # 1. Never act on a dirty or diverged local repo.
    if git("status", "--porcelain").stdout.strip():
        return fail("local working tree is dirty; not syncing")
    behind = git("rev-list", "--count", "HEAD..@{u}").stdout.strip()
    if behind not in ("", "0"):
        if git("merge", "--ff-only", "--quiet", "@{u}").returncode != 0:
            return fail("could not fast-forward from origin; manual sync needed")

    # 2. Log in to the production admin panel (unified login).
    login_html = fetch("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', login_html)
    if not match:
        return fail("no CSRF token on production login page")
    final_url = post_form(
        "/login",
        {"csrf_token": match.group(1), "identifier": ADMIN_USER, "password": ADMIN_PASS},
        SITE_URL + "/login",
    )
    if not final_url.rstrip("/").endswith("/admin"):
        return fail("production admin login failed (check credentials in .env)")

    # 3. Export public content (accounts excluded by the app itself).
    export = json.loads(fetch("/admin/database/export"))

    # 4. Compare against the tracked seed's public keys.
    seed_path = REPO / "site_data.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    seed_public = {k: v for k, v in seed.items() if k not in PRIVATE_KEYS}
    changed = [k for k in sorted(set(export) | set(seed_public)) if export.get(k) != seed_public.get(k)]

    # 4b. Database-only sync: three-way merge the production export into the
    # local site.db (gitignored, never committed), production wins conflicts.
    notes = []
    baseline = {}
    if SYNC_STATE.exists():
        try:
            baseline = json.loads(SYNC_STATE.read_text(encoding="utf-8"))
            if not isinstance(baseline, dict):
                baseline = {}
        except ValueError:
            baseline = {}
    try:
        db_changed, push_up, skipped = merge_local_db(export, baseline)
    except (sqlite3.Error, OSError) as exc:
        return fail("local DB merge failed, seed sync continues next run: %s" % str(exc)[:120])
    if db_changed:
        notes.append("local site.db merged")
    if push_up:
        try:
            db_page = fetch("/admin/database")
            token = re.search(r'name="csrf_token" value="([^"]+)"', db_page)
            if not token:
                raise ValueError("no CSRF token on database page")
            payload = json.dumps(
                {k: read_local_db().get(k) for k in push_up}, ensure_ascii=False
            ).encode("utf-8")
            post_multipart(
                "/admin/database/import",
                {"csrf_token": token.group(1)},
                {"import_file": ("ila-local-additions.json", payload, "application/json")},
                SITE_URL + "/admin/database",
            )
            notes.append("pushed up local-only keys: %s" % ", ".join(push_up[:5]))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            notes.append("local-only keys kept locally (push-up failed: %s)" % str(exc)[:100])
            push_up = []
    for key in skipped:
        notes.append("kept local edit to '%s' (deleted on production)" % key)
    if not changed and not notes:
        return 0  # everything in sync — stay quiet

    # 5. Dated content backup (only when production actually changed something
    # we track), then rewrite the seed: production content wins for public
    # keys, local credentials (admin_users etc.) are preserved verbatim, and
    # key order follows the existing seed.
    backup_dir = REPO / "backups"
    backup_dir.mkdir(exist_ok=True)
    if changed:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (backup_dir / f"prod-content-{stamp}.json").write_text(
            json.dumps(export, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for old in sorted(backup_dir.glob("prod-content-*.json"))[:-KEEP_BACKUPS]:
            old.unlink()

        ordered = {}
        for key in seed:
            if key == "seed_version":
                continue
            if key in PRIVATE_KEYS:
                ordered[key] = seed[key]  # accounts/credentials never come from the export
            else:
                ordered[key] = export.get(key, seed[key])  # production content wins
        for key in export:
            if key not in ordered:
                ordered[key] = export[key]
        ordered["seed_version"] = int(seed.get("seed_version", 0) or 0) + 1
        seed_path.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        # 6. Commit and push (message style matches the built-in publisher).
        labels = ", ".join(changed[:5])
        if git("add", "--", "site_data.json").returncode != 0:
            return fail("could not stage site_data.json")
        if git("diff", "--cached", "--quiet").returncode != 0:
            if git("commit", "-m", f"Content: sync production panel edits ({labels})").returncode != 0:
                return fail("git commit failed")
            push = git("push", "@{u}")
            if push.returncode != 0:
                # One retry after syncing with origin (e.g. a deploy or the auto-pull
                # cron moved the branch between our fetch and push). Push failures are
                # transient (network/keychain), so back off briefly, then refresh before
                # retrying so we never force a non-fast-forward push.
                import time as _time

                _time.sleep(20)
                git("pull", "--rebase", "--quiet", "@{u}")
                push = git("push", "@{u}")
            if push.returncode != 0:
                detail = ((push.stderr or "") + (push.stdout or "")).strip().splitlines()
                detail = " | ".join(detail[-4:])
                return fail(f"git push failed (commit kept locally; will retry next run): {detail}"[:300])
            message = f"synced production content: {labels} ({len(changed)} keys) -> {git('rev-parse', '--short', 'HEAD').stdout.strip()}"
            log(message)
            print(message)

    # 7. Record this export as the merge baseline and report DB-only activity.
    # site.db itself is gitignored — it syncs database-to-database only.
    try:
        SYNC_STATE.write_text(json.dumps(export, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return fail("could not save sync baseline: %s" % str(exc)[:120])
    for note in notes:
        log("db-sync: " + note)
        print("db-sync: " + note)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        sys.exit(fail(str(exc)[:200]))

