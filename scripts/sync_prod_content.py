#!/usr/bin/env python3
"""Publish production admin-panel content to git (local bridge).

Render's built-in publisher (GIT_CONTENT_COMMIT) needs a GITHUB_TOKEN secret on
Render that is not configured. Until it is, this script closes the loop from
here: it logs into the production admin panel, exports public content, and when
it differs from site_data.json, commits and pushes it (commit message "Content:
..."), exactly like the built-in publisher would. It also keeps dated content
backups under backups/ so panel content can be restored without a DB snapshot.

Credentials come from .env (gitignored): PROD_ADMIN_USER / PROD_ADMIN_PASSWORD,
falling back to ADMIN_USERNAME / ADMIN_PASSWORD. Stdlib only — no new deps.
Run via cron every 15 minutes; quiet when nothing changed.
"""
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
SITE_URL = os.environ.get("PROD_SITE_URL", "https://initiative4legalaid.org").rstrip("/")
USER_AGENT = "ila-content-sync/1.0"
PRIVATE_KEYS = frozenset({"admin_users", "users", "admin_account", "seed_version"})
KEEP_BACKUPS = 30
LOG_FILE = Path.home() / "Library/Logs/ila-content-sync.log"


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
    if not changed:
        return 0  # in sync — stay quiet

    # 5. Dated content backup, then rewrite the seed preserving key order.
    backup_dir = REPO / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (backup_dir / f"prod-content-{stamp}.json").write_text(
        json.dumps(export, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for old in sorted(backup_dir.glob("prod-content-*.json"))[:-KEEP_BACKUPS]:
        old.unlink()

    ordered = {k: seed[k] for k in seed if k in export or k not in PRIVATE_KEYS}
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
    if git("diff", "--cached", "--quiet").returncode == 0:
        return 0  # nothing actually changed after writing
    if git("commit", "-m", f"Content: sync production panel edits ({labels})").returncode != 0:
        return fail("git commit failed")
    if git("push", "--quiet", "@{u}").returncode != 0:
        return fail("git push failed (commit kept locally; will retry next run)")
    message = f"synced production content: {labels} ({len(changed)} keys) -> {git('rev-parse', '--short', 'HEAD').stdout.strip()}"
    log(message)
    print(message)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        sys.exit(fail(str(exc)[:200]))

