# DNS cutover — pointing initiativeforlegalaid.org at Render
# Production service: https://https-initiativeforlegalaid-org-1.onrender.com
# (srv-dakep4bm8hqs73ebt5t0) — LIVE and verified 2026-09-15.
# Current DNS: A @ → 23.153.104.141, A www → 23.153.104.141 (OraWebHost WordPress),
# nameservers ns1/ns2.orawebhost.co.ke → DNS is edited in OraWebHost's panel (cPanel Zone Editor).

## STEP 0 — Pre-flight (do first)
- [ ] Confirm you can log in to https://https-initiativeforlegalaid-org-1.onrender.com/login (Free).
- [ ] Set ADMIN_BOOTSTRAP=0 in Render → Environment (done after first login).
- [ ] Confirm Render → Disks has the disk at /opt/render/project/src/data.
- [ ] Optional: back up the old WordPress site (OraWebHost export) for content reference.

## STEP 1 — Add domains in Render (5 min)
1. Render Dashboard → your service → Settings → scroll to **Custom Domains**.
2. **+ Add Custom Domain** → enter `initiativeforlegalaid.org` → Save.
3. Add a second: `www.initiativeforlegalaid.org`.
4. Render will display the exact DNS records to create (usually a CNAME for `www`
   pointing at your onrender URL, and an A record / ALIAS for the apex `@`).
   **Use the values Render shows — they are service-specific.**

## STEP 2 — Edit DNS at OraWebHost (5 min)
1. Log in to OraWebHost cPanel → **Domains → Zone Editor** (or "Advanced DNS").
2. For `initiativeforlegalaid.org.` (record name `@`):
   - EDIT the existing A record `23.153.104.141` → Render's apex target
     (the A-record IP or ALIAS shown in Render's Custom Domains page). TTL 300.
3. For `www`:
   - EDIT the existing A/www record → CNAME pointing to
     `https-initiativeforlegalaid-org-1.onrender.com` (or the exact value Render shows). TTL 300.
4. Save both. If the panel won't let you change record type, delete the www A record
   and create a new CNAME www → onrender URL.

## STEP 3 — Verify in Render + worldwide (up to 1 h, TTL 3600 → up to 1 h wait)
- Render Custom Domains page shows "Verified" for both, then auto-provisions TLS
  (Let's Encrypt) and redirects all HTTP → HTTPS. Nothing to install.
- Check from anywhere:
    dig +short initiativeforlegalaid.org          # should return Render's IP
    dig +short www.initiativeforlegalaid.org      # CNAME → onrender
    curl -s -o /dev/null -w 'root:%{http_code} final:%{url_effective}\n' -L https://initiativeforlegalaid.org/
    curl -s -o /dev/null -w 'www:%{http_code}  final:%{url_effective}\n' -L https://www.initiativeforlegalaid.org/
- Expect 200 with final URL https://initiativeforlegalaid.org/ and the Flask homepage
  (grep for "Civic and Legal Education" to confirm content, not WordPress).

## STEP 4 — Cleanup / rollback
- Keep the old OraWebHost WordPress hosting active for 48 h, then cancel/migrate.
- Rollback: point both records back to A 23.153.104.141 (propagates within TTL 300).
- After 48 h stable, raise TTL back to 3600.

