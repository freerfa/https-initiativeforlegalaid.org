# Initiative for Legal Aid — Project Handoff

> **Living document.** Any human or AI picking up this project: start here.
> Last updated: 2026-09-23. Status: **LIVE on Render: https://https-initiativeforlegalaid-org-p51u.onrender.com** (+ local dev http://127.0.0.1:5001). Production domain decided 2026-09-23: **`initiative4legalaid.org` (with "4"), registered at Hostinger** — cutover steps in `deploy/DNS_CUTOVER.md` (top section). Old `initiativeforlegalaid.org` (OraWebHost/Truehost) is no longer the target; its mail (MX/SPF) stays untouched and unaffected.
> Update this file + `CHANGELOG.md` on every change (see §9).

## 1. What this project is

Flask website for **Initiative for Legal Aid** (South Sudan legal-aid NGO).

- Public site: home (hero, about, mission, services, projects, testimonials, gallery, contact), **`/leadership`** (team+photos, organogram, impact indicators, knowledge centre, accountability policies), **`/partnerships`** (UNFPA + CESYU partner cards, ceremony artwork, 26 institution categories, 10 partner-value cards, donor due diligence) + dynamic custom pages (`/page/<slug>`).
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
- **PRODUCTION: Render web service** `srv-dakep4bm8hqs73ebt5t0` — https://https-initiativeforlegalaid-org-p51u.onrender.com (auto-deploys on push to `main`; build `pip install -r requirements.txt`, start `gunicorn -w 2 -b 0.0.0.0:$PORT app:app`; DB on persistent disk `DATA_DIR=/opt/render/project/src/data` auto-seeds on first boot). ⚠️ **Root Directory in Render Settings must stay EMPTY** — a URL accidentally entered there caused a ~1h outage (see §8 #11).
- Admin accounts: `Free` and `admin` (both in site.db admin_users; hashes, never plaintext).
- Mail: domain MX → `mail.initiativeforlegalaid.org` (OraWebHost). Mailboxes `info@/emmanuel@/nicodemus@/modi@initiativeforlegalaid.org` must be **created in OraWebHost cPanel** (Email → Email Accounts). During DNS cutover, NEVER touch mail/MX/SPF records.

### Working tree
Clean as of 2026-09-15 (all work committed + pushed to `origin/main`, repo renamed by GitHub to `freerfa/https-initiativeforlegalaid.org`).

## 3. Repo map

```
/app.py                  # routes, auth, storage, uploads
/site.db                 # live data: site_data(id, data JSON)
/site_data.json          # seed only, used by ensure_db() on fresh DATA_DIR
/requirements.txt        # Flask 3.1.3, Flask-WTF, filetype, gunicorn 23.0.0, ...
/.env / .env.example     # SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD, DATA_DIR
/render.yaml             # Render Blueprint config
/Dockerfile docker-compose.yml Procfile pyproject.toml requirements-prod.txt  # packaging
/deploy/                 # deploy.sh (VPS recipe), ila.service, nginx-ila.conf,
                         # MIGRATION_CHECKLIST.md, DNS_CUTOVER.md (mail warning inside)
/templates/
  base.html              # layout, role-aware nav, flash, footer w/ social links
  index.html             # homepage
  leadership.html        # /leadership (team, organogram, indicators, policies)
  partnerships.html      # /partnerships (UNFPA, CESYU, institutions, donor info)
  login.html             # unified login (all login URLs)
  register.html          # member registration
  user_account.html      # member page
  admin_dashboard.html   # admin CMS
  admin_login.html       # legacy/unused
  user_login.html        # legacy/unused
  page.html 404.html
/static/style.css        # styling incl. responsive breakpoints + partnerships/leadership styles
/static/uploads/         # seed images committed to git (hero/gallery/testimonial/leadership/partners);
                         # NEW admin uploads stay gitignored (§8 #10) and are EPHEMERAL on Render
/PROJECT_HANDOFF.md      # this file — start here
/CHANGELOG.md            # append every change

## 4. Setup & run (macOS / Linux)

Run: `PORT=5001 python app.py` (port 5000 is taken by macOS AirPlay). Install with `python -m pip install -r requirements.txt` (bare `pip` shim is missing). Kill stale servers: `lsof -ti:5001 | xargs kill -9`. Open http://127.0.0.1:5001/ and http://127.0.0.1:5001/login.

## 5. Routes (all)

GET `/` homepage. GET `/leadership` team/governance/impact. GET `/partnerships` partners/donors. GET `/page/<slug>` custom page. GET+POST `/login` unified login (role auto-detected). GET+POST `/admin/login` alias same theme/logic. GET+POST `/user/login` alias same theme/logic. GET+POST `/register` member registration (auto-login persistent). GET `/logout` member logout (keeps admin session). GET `/account` user_required member page. GET `/admin/logout` clears session. GET `/admin` login_required dashboard. POST `/admin/update` bulk content + uploads. POST `/admin/photo/<target>/update` and `/delete`. POST `/admin/custom-section/create` and `/<int:index>/delete`. POST `/admin/page/create` and `/<slug>/delete`. POST `/admin/account` own credentials. POST `/admin/users/create` and `/users/<username>/delete`.

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
9. 2026-09-15 Hamburger nav-toggle appeared unstyled/broken (looked like a dead white button). Symptom: user saw a plain bordered square that did nothing. Cause: browser cached the pre-responsive stylesheet while HTML already had the toggle (old CSS + new HTML = orphaned element). Fix: cache-bust query string on style.css link (bump ?v= on every CSS change: 20260915b→c→d) + moved toggle JS to addEventListener. Toggle was removed then re-added per user request; final state: hidden on desktop (>768px), shown and functional on ≤768px. Verify: live CSS contains `nav-toggle{display:none}` default and `display:inline-flex` only inside @media (max-width:768px).
10. 2026-09-15 All photos 404 on Render. Symptom: hero/gallery/testimonial images missing on production. Cause: seed images existed only in local static/uploads/, which .gitignore excludes → fresh Render checkout had empty uploads dir. Fix: `git add -f` the 17 seed images + .gitignore whitelist exceptions (!static/uploads/{hero,hero-alt,gallery-*,testimonial-*}.jpg etc.) so seed images stay tracked while new admin uploads stay ignored. Verify: all image URLs 200 on live site. KNOWN LIMITATION: images uploaded via admin on Render live on the ephemeral instance filesystem and reset to seeds on redeploy — fix by pointing UPLOAD_FOLDER at DATA_DIR disk (not yet done).
11. 2026-09-15 SITE DOWN ~1h (restart loop). Symptom: Render log repeating `/home/render/runner.sh: line 15: cd: /opt/render/project/src/https-initiativeforlegalaid-org-p51u.onrender.com: No such file or directory`; site unreachable. Cause: the service URL was accidentally pasted into Render Settings → Root Directory, so the runner tried to cd into a nonexistent directory before every start. Fix: clear Root Directory to EMPTY in Render Settings → Save → Manual Deploy. Verify: deploy log shows normal `Cloning` → `gunicorn -w 2 -b 0.0.0.0:$PORT app:app` → `Your service is live`; all pages 200. LESSON: Root Directory must stay empty for this repo (app.py is at repo root).
12. 2026-09-15 Domain DNS typo risk. Symptom: user added `initiative4legalaid.org` (with "4") as custom domain in Render — domain did not exist then. ORIGINAL fix was to remove the entry and use `initiativeforlegalaid.org` (f-o-r). **UPDATE 2026-09-23: the user has since REGISTERED `initiative4legalaid.org` at Hostinger, and it is now the decided production domain — keep/verify that Render custom-domain entry instead of deleting it. See the CURRENT PLAN section at the top of deploy/DNS_CUTOVER.md.**
13. 2026-09-15 Mail-breakage risk during DNS cutover. Symptom: none yet (prevented). Cause: MX + mail A + SPF records for initiativeforlegalaid.org live on the OLD OraWebHost server; a naive "change all A records" cutover would kill @initiativeforlegalaid.org email. Fix: DNS_CUTOVER.md now warns: change ONLY `A @` → 216.24.57.1 and `CNAME www` → https-initiativeforlegalaid-org-p51u.onrender.com; never touch mail/MX/SPF. Also: mailboxes (info@, emmanuel@, nicodemus@, modi@) must be created in OraWebHost cPanel. Verify: `dig MX initiativeforlegalaid.org` still returns mail host after cutover; test send/receive.

## 9. How to update these docs (humans + AI)

After any code or config change: append a row to CHANGELOG.md (date, what, files, verify) and update section 2 above if behaviour/ports/credentials changed. After any bug found or fixed: append a numbered entry to section 8 (symptom, cause, fix, verify). Keep this file the single entry point; README stays short and links here. Before committing: python -m py_compile app.py, curl touched routes, update docs, then git add and commit.

## 10. Production checklist (as of 2026-09-15)

- [x] Strong SECRET_KEY via env (Render Generate); .env never committed
- [x] Deployed to Render web service (gunicorn 2 workers, auto-deploy on push to main)
- [x] Persistent disk mounted at /opt/render/project/src/data (DB survives redeploys; auto-seeds on first boot)
- [x] Admin login verified on Render; ADMIN_BOOTSTRAP set to 0 after first login
- [x] Seed photos committed to repo; all image URLs 200 on live site
- [x] Content parity with old WordPress site (6 services, 4 projects) + incorporated companion sites (/leadership, /partnerships) with 17 real photos
- [x] Nav/footer updated: Leadership + Partnerships links, real social URLs (Facebook/LinkedIn/X @LegalAid4SS)
- [x] Root Directory in Render Settings cleared (was cause of §8 #11 outage) — MUST STAY EMPTY
- [ ] **DNS cutover for `initiative4legalaid.org` at HOSTINGER hPanel** (decided 2026-09-23): delete Hostinger parking records (A @ 5.252.75.81, A @ 88.222.223.77, CNAME www → ...cdn.hstgr.net); add `A @ → 216.24.57.1` and `CNAME www → https-initiativeforlegalaid-org-p51u.onrender.com`. See deploy/DNS_CUTOVER.md CURRENT PLAN section.
- [ ] **Render Custom Domains**: ensure both `initiative4legalaid.org` + www are added to service srv-dakep4bm8hqs73ebt5t0; click Retry Verification after Hostinger DNS save; Render issues HTTPS cert automatically. (The 2026-09-15 "typo" concern is resolved — the "4" domain now exists and is the production target, see §8 #12 update.)
- [ ] **Create mailboxes** in OraWebHost cPanel (Email → Email Accounts): info@, emmanuel@, nicodemus@, modi@initiativeforlegalaid.org
- [ ] **Replace placeholder content**: Protection Coordinator name+photo on /leadership; confirm CESYU ceremony venue; review impact-indicator "figures to be verified" wording with staff
- [ ] **Rotate admin passwords** before real users (Free/Contact12 + admin/admin123 were shared in chat during dev)
- [ ] **Render paid plan decision**: free tier sleeps ~15 min idle (~50s cold start) and had an unexplained ~1h outage; Starter ($7/mo) = always-on
- [ ] **Upload persistence**: point UPLOAD_FOLDER at DATA_DIR disk so admin photo uploads survive redeploys (§8 #10)
- [ ] Remove legacy unused templates admin_login.html and user_login.html (zero code references confirmed)
- [ ] Back up site.db (Render shell or admin export) before bulk edits
- [ ] Post-cutover verification: https://initiative4legalaid.org 200 + cert valid; `dig MX initiativeforlegalaid.org` unchanged (its mail is separate, on OraWebHost); update this checklist + CHANGELOG