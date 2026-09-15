# Initiative for Legal Aid — Project Handoff

> **Living document.** Any human or AI picking up this project: start here.
> Last updated: 2026-09-15. Status: **LIVE on Render: https://https-initiativeforlegalaid-org-1.onrender.com** (+ local dev http://127.0.0.1:5001).
> Update this file + `CHANGELOG.md` on every change (see §9).

## 1. What this project is

Flask website for **Initiative for Legal Aid** (South Sudan legal-aid NGO).

- Public site: home (hero, about, mission, services, projects, testimonials, gallery, contact) + dynamic custom pages (`/page/<slug>`).
- **Admin dashboard** (`/admin`): edit homepage text, contact details, services/projects/testimonials, custom sections, custom pages, photos, admin users, own credentials.
- **Member accounts**: registration (`/register`), unified login (`/login`), account page (`/account`).
- Production target: `https://initiativeforlegalaid.org/` — deploy this Flask app behind Nginx/Apache + HTTPS.

## 2. Current state (pick up from here)

- Branch `main` (commit `68949b1` + uncommitted work below).
- `app.py` = whole backend (~750 lines, single file).
- Storage: **SQLite `site.db`** (table `site_data`, row `id=1`, col `data` = JSON blob). Legacy `site_data.json` on disk but **not read** — `load/save_data()` use `site.db` only.
- Auth: **unified login** — `/login`, `/admin/login`, `/user/login` render `templates/login.html`; role auto-detected (admin → `/admin`, user → `/account`). Sessions **persistent 30 days** (`PERMANENT_SESSION_LIFETIME`, `session.permanent=True`).
- Security: `CSRFProtect` on, every POST form has `csrf_token`; uploads checked by extension allowlist + magic bytes (`filetype`); `secure_filename`; 16 MB cap; `pbkdf2:sha256` hashes.
- Deps in `.venv` (Python 3.9 macOS arm64), pinned in `requirements.txt` (incl. gunicorn==23.0.0).
- Live dev instance: port **5001** (5000 taken by macOS AirPlay). Log `/tmp/ila_app.log`.
- **PRODUCTION: Render web service** `srv-dakep4bm8hqs73ebt5t0` — https://https-initiativeforlegalaid-org-1.onrender.com (main @ d29c596, start `gunicorn -w 2 -b 0.0.0.0:$PORT app:app`, DATA_DIR=/opt/render/project/src/data on persistent disk). Deploys auto-trigger on push to `main`.
- Admin accounts: `Free` and `admin` (both in site.db admin_users; hashes, never plaintext).

### Uncommitted working changes (do not lose)
- `M app.py` — CSRF, secure uploads, sqlite backend, unified login, persistent sessions.
- `M templates/base.html` — role-aware nav (Login / Dashboard / username).
- `M templates/admin_login.html`, `admin_dashboard.html`, `index.html` — CSRF tokens injected.
- `M static/style.css` — `.remember-row` style added.
- `??` new: `templates/login.html` (unified), `register.html`, `user_account.html`, `user_login.html` + `admin_login.html` (legacy, unused), `404.html`, `page.html`, `requirements.txt`, `site.db`, `site_data.json`, `.env`, `static/uploads/`.

## 3. Repo map

```
/app.py                  # routes, auth, storage, uploads
/site.db                 # live data: site_data(id, data JSON)
/site_data.json          # LEGACY seed only, not read
/requirements.txt        # Flask 3.1.3, Flask-WTF, filetype, ...
/.env / .env.example     # SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD
/templates/
  base.html              # layout, role-aware nav, flash, footer
  login.html             # unified login (all login URLs)
  register.html          # member registration
  user_account.html      # member page
  admin_dashboard.html   # admin CMS
  admin_login.html       # legacy/unused
  user_login.html        # legacy/unused
  index.html page.html 404.html
/static/style.css        # styling incl. .remember-row
/static/uploads/         # uploaded images
/PROJECT_HANDOFF.md      # this file — start here
/CHANGELOG.md            # append every change

## 4. Setup & run (macOS / Linux)

Run: `PORT=5001 python app.py` (port 5000 is taken by macOS AirPlay). Install with `python -m pip install -r requirements.txt` (bare `pip` shim is missing). Kill stale servers: `lsof -ti:5001 | xargs kill -9`. Open http://127.0.0.1:5001/ and http://127.0.0.1:5001/login.

## 5. Routes (all)

GET `/` homepage. GET `/page/<slug>` custom page. GET+POST `/login` unified login (role auto-detected). GET+POST `/admin/login` alias same theme/logic. GET+POST `/user/login` alias same theme/logic. GET+POST `/register` member registration (auto-login persistent). GET `/logout` member logout (keeps admin session). GET `/account` user_required member page. GET `/admin/logout` clears session. GET `/admin` login_required dashboard. POST `/admin/update` bulk content + uploads. POST `/admin/photo/<target>/update` and `/delete`. POST `/admin/custom-section/create` and `/<int:index>/delete`. POST `/admin/page/create` and `/<slug>/delete`. POST `/admin/account` own credentials. POST `/admin/users/create` and `/users/<username>/delete`.

Guards: login_required = admin only else redirect /login?next=/admin... ; user_required = user only else /login?next=... ; next honoured when safe.

## 6. Auth design (must-know)

find_account(site, identifier) checks admin_users first then users (username or email, case-insensitive). Admin session keys: logged_in=True, username, role=admin. User keys: user_logged_in=True, user_username, role=user. session.permanent=True on login/register, cookie 30 days. Keep-me-logged-in checkbox default checked (session always persistent for now). Registration blocks empty fields, pw<8, mismatch, dup username/email, admin-reserved username. Admin goes to /admin, user to /account.

## 7. Storage design (must-know)

get_db_connection() sqlite3 + Row factory. load_data() merges DB JSON over default_site_data() plus backfills about/mission/service/project images from gallery. save_data() upserts row id=1. Schema: site_data(id INTEGER PK, data JSON), one blob, no per-entity tables. Recreate with sqlite3 site.db CREATE TABLE IF NOT EXISTS site_data(id INTEGER PRIMARY KEY, data JSON); then save once via app or insert site_data.json as row 1. Back up site.db before bulk edits.

## 8. Issues and resolutions (append-only, never delete)

1. 2026-09-14 Port 5000 unusable on macOS. Symptom: curl :5000 gives 403 Server AirTunes, Flask Address already in use. Cause: macOS ControlCenter/AirPlay occupies :5000. Fix: run PORT=5001; get_local_port() falls back to random port. Verify: curl -I 127.0.0.1:5001/ is 200.
2. 2026-09-14 No CSRF protection. Symptom: grep csrf found nothing. Cause: CSRFProtect never added. Fix: CSRFProtect(app) plus hidden csrf_token in all 13 POST forms. Verify: POST without token is 400.
3. 2026-09-14 Unsafe uploads. Symptom: handle_upload only stripped chars, any extension saved. Cause: no extension or MIME check, no secure_filename, overwrite possible. Fix: ALLOWED_EXTENSIONS png/jpg/jpeg/gif/webp, filetype magic-byte check, secure_filename, counter on collision, flash plus fallback on reject. Verify: .py renamed .jpg is rejected.
4. 2026-09-14 JSON flat-file race risk. Symptom: every edit rewrites whole site_data.json. Cause: no locking. Fix: migrated to site.db single JSON row; load/save_data use SQLite. Verify: concurrent edits safe, homepage loads from DB.
5. 2026-09-14 Zombie app.py processes. Symptom: ps showed 10+ PIDs, Port 5001 is in use. Cause: background runs never killed. Fix: kill -9 pids or lsof -ti:5001 | xargs kill -9, single nohup instance. Verify: one PID, curl :5001/ is 200.
6. 2026-09-14 Split login themes plus session lost on browser close. Symptom: separate admin_login/user_login templates, non-persistent cookie. Cause: split views, session.permanent never set. Fix: unified templates/login.html for all login URLs, find_account role routing, PERMANENT_SESSION_LIFETIME 30d plus session.permanent=True, role-aware nav. Verify: admin login 302 to /admin 200, wrong pw shows Invalid login details.
7. 2026-09-14 .venv/bin/pip missing. Symptom: zsh command not found pip. Cause: pip shim absent. Fix: use .venv/bin/python -m pip everywhere. Verify: python -m pip show Flask OK.
8. 2026-09-15 Render deploy failed with gunicorn: command not found (exit 127). Symptom: build succeeded but start ran `gunicorn your_application.wsgi` (Render placeholder) → bash: line 1: gunicorn: command not found. Cause: (a) gunicorn was only in requirements-prod.txt while the dashboard build command was `pip install -r requirements.txt`; (b) start command left as Render's placeholder instead of our app entry. Fix: added gunicorn==23.0.0 to requirements.txt (commit d29c596) and set Start Command in Render dashboard to `gunicorn -w 2 -b 0.0.0.0:$PORT app:app` (Render injects $PORT; hardcoding a port fails health checks). Verify: deploy log shows gunicorn-23.0.0 installed, `[INFO] Booting worker`, `Your service is live`, external home 200.

## 9. How to update these docs (humans + AI)

After any code or config change: append a row to CHANGELOG.md (date, what, files, verify) and update section 2 above if behaviour/ports/credentials changed. After any bug found or fixed: append a numbered entry to section 8 (symptom, cause, fix, verify). Keep this file the single entry point; README stays short and links here. Before committing: python -m py_compile app.py, curl touched routes, update docs, then git add and commit.

## 10. Production checklist (in progress)

- [x] Strong SECRET_KEY via env (Render Generate) — done at service creation; never commit .env
- [x] Deployed to Render web service (gunicorn 2 workers, start `gunicorn -w 2 -b 0.0.0.0:$PORT app:app`)
- [x] Admin accounts exist: Free/Contact12 + admin/admin123 (site.db admin_users) — **rotate before real users**
- [ ] **Verify admin login works on Render** (if it fails, add ADMIN_BOOTSTRAP=1 + ADMIN_USERNAME/ADMIN_PASSWORD env vars)
- [ ] **Set ADMIN_BOOTSTRAP=0** in Render Environment after first successful login
- [ ] **Confirm Render disk** mounted at /opt/render/project/src/data (else every redeploy wipes edits)
- [ ] **Custom domain cutover**: Render → Settings → Custom Domains → add initiativeforlegalaid.org + www; create DNS records at registrar (current WP host: A 23.153.104.141, ns orawebhost.co.ke)
- [ ] Content review on Render instance (uploads/uploads dir on disk; placeholder contact@domain.com → real inbox)
- [ ] Consider Render paid plan (free tier sleeps after ~15 min idle, ~50s cold start)
- [ ] Remove legacy unused templates admin_login.html and user_login.html or confirm no references
- [ ] Back up site.db (download from Render shell or via admin export) before bulk edits