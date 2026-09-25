# Initiative for Legal Aid — website + admin CMS

> **New here? Start with [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md)** — full handoff: current state, routes, auth/storage design, issues log, production checklist.

Flask site for Initiative for Legal Aid (South Sudan) with a unified login (admins → dashboard, members → account), persistent sessions, and an admin dashboard to edit homepage text, contact details, services/projects/testimonials, custom sections/pages, and photos.

## Quick start (local dev)

```bash
cd /Users/freemirghani/Downloads/Initiativeforlegalaid.org
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env   # then fill in SECRET_KEY + ADMIN_* (see below)
PORT=5001 python app.py   # port 5000 is taken by macOS AirPlay
```

Open http://127.0.0.1:5001/ · login http://127.0.0.1:5001/login · register http://127.0.0.1:5001/register

## First admin account

1. In `.env`, set `ADMIN_USERNAME`, a strong `ADMIN_PASSWORD`, and `ADMIN_BOOTSTRAP=1`.
2. Start the app once and log in — the admin is created from env.
3. Set `ADMIN_BOOTSTRAP=0` and restart. Env never overrides stored admins afterwards.

## Production

- Set `SECRET_KEY` (≥32 random chars), real `ADMIN_*`, `FLASK_ENV=production`, never commit `.env`.
- Serve with gunicorn/waitress behind Nginx/Apache + HTTPS for `https://initiativeforlegalaid.org/`, e.g. `gunicorn -w 3 -b 127.0.0.1:8000 app:app` proxied by Nginx.
- To publish each public admin-panel content save to Git, set `GIT_CONTENT_COMMIT=1` and add a `GITHUB_TOKEN` secret in the Render service environment. The token needs **Contents: read and write** permission for this repository. Never put the token in Git or `.env`; without it, content saves remain database-only and no warning is shown.
- Back up `site.db` (live data) regularly; see `PROJECT_HANDOFF.md` §7/§10.

