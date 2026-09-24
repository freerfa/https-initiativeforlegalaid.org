# DNS cutover — pointing initiativeforlegalaid.org at Render
# Production service: https://https-initiativeforlegalaid-org-1.onrender.com
# (srv-dakep4bm8hqs73ebt5t0)
# ============================================================
# CURRENT PLAN (decided 2026-09-23): initiative4legalaid.org (with "4")
# >>> STATUS: CUTOVER COMPLETE — verified 2026-09-23, re-verified 2026-09-24 <<<
# ============================================================
# FINAL ZONE STATE at Hostinger for initiative4legalaid.org:
#   A      @    -> 216.24.57.1                                       (Render)
#   CNAME  www  -> https-initiativeforlegalaid-org-p51u.onrender.com
#   MX / TXT / autodiscover / autoconfig -> untouched Hostinger defaults
#
# WHAT ACTUALLY HAPPENED (differed from the plan in STEP 1 below — the apex
# was NOT on plain A records but on an ALIAS to Hostinger's CDN, which is why
# the first edit looked applied yet the Hostinger placeholder kept serving):
#   1. DELETED  ALIAS @ -> initiative4legalaid.org.cdn.hstgr.net   (the blocker)
#   2. ADDED    A     @ -> 216.24.57.1
#   3. DELETED  A     ftp -> 216.24.57.1   (Render IP first entered on the
#               wrong record name; removed in cleanup)
#   4. www CNAME was already correct — left as-is.
#   5. Render -> Settings -> Custom Domains: both domains Verified; TLS
#      certificate issued automatically.
#
# VERIFIED 2026-09-24 from public resolvers:
#   dig @8.8.8.8 +short A initiative4legalaid.org          -> 216.24.57.1
#   dig @8.8.8.8 +short CNAME www.initiative4legalaid.org  -> ...onrender.com.
#   curl -L https://initiative4legalaid.org/               -> 200 (HTTP/2), apex kept
#   <title>                                                -> Initiative for Legal Aid South Sudan
#   TLS                                                    -> subject CN=initiative4legalaid.org,
#                                                             issuer Google Trust Services (WE1),
#                                                             notAfter 2026-12-22
#
# NOTE: the older "...-1.onrender.com" hostname in the notes below is
# historical. The authoritative custom-domain target is
# https-initiativeforlegalaid-org-p51u.onrender.com.
#
# STEPS 1-3 below are kept as the reference procedure for a re-cutover or a
# move to another host; the ROLLBACK note still applies.
#
# Decision: the production domain is `initiative4legalaid.org`, registered at
# HOSTINGER (hPanel). The historical plans further below for
# `initiativeforlegalaid.org` (OraWebHost/Truehost) are kept as reference.
#
# Verified DNS before cutover (2026-09-23):
#   NS    initiative4legalaid.org -> aster/helios.dns-parking.com (Hostinger parking)
#   A     @      -> 5.252.75.81   (Hostinger default page)
#   A     @      -> 88.222.223.77 (Hostinger default page)
#   CNAME www    -> www.initiative4legalaid.org.cdn.hstgr.net (Hostinger)
#   Render app (srv-dakep4bm8hqs73ebt5t0) LIVE, HTTP 200 at
#   https://https-initiativeforlegalaid-org-p51u.onrender.com
#
# STEP 1 — Hostinger hPanel (only you can log in):
#   hPanel -> Domains -> initiative4legalaid.org -> DNS / Nameservers (DNS Zone):
#   1. DELETE the Hostinger parking records:
#        A  @   -> 5.252.75.81
#        A  @   -> 88.222.223.77
#        CNAME www -> www.initiative4legalaid.org.cdn.hstgr.net
#   2. ADD:  A     @    -> 216.24.57.1     (Render apex IP, TTL 3600 or default)
#   3. ADD:  CNAME www  -> https-initiativeforlegalaid-org-p51u.onrender.com
#   If Render's Custom Domains page shows different values, USE THOSE instead.
#   Email note: this domain has no existing mailboxes; leave/remove any default
#   Hostinger MX records freely. The org's real email (MX, mail A, SPF) belongs
#   to initiativeforlegalaid.org on OraWebHost — never touch those.
#
# STEP 2 — Render Dashboard (only you can log in):
#   Service srv-dakep4bm8hqs73ebt5t0 -> Settings -> Custom Domains:
#   1. Ensure BOTH `initiative4legalaid.org` and `www.initiative4legalaid.org`
#      are added (the entry once considered a typo in §8 #12 is now CORRECT —
#      keep/verify it instead of deleting).
#   2. Click Retry Verification after saving the Hostinger DNS records.
#   Render auto-provisions the Let's Encrypt cert + HTTP->HTTPS redirect.
#
# STEP 3 — Verify (up to ~1 h for propagation):
#   dig +short A initiative4legalaid.org          # expect 216.24.57.1
#   dig +short CNAME www.initiative4legalaid.org  # expect ...onrender.com
#   curl -s -o /dev/null -w '%{http_code} %{url_effective}\n' -L https://initiative4legalaid.org/
#   Expect 200 + Flask homepage (grep "Civic and Legal Education"), not Hostinger default.
#
# ROLLBACK: in hPanel restore A @ -> 5.252.75.81 and CNAME www ->
#   www.initiative4legalaid.org.cdn.hstgr.net, then remove the custom domains in Render.
#
# ============================================================
# HISTORICAL: initiativeforlegalaid.org (f-o-r) — NOT the production target since 2026-09-23
# ============================================================
#
# RE-CUTOVER NOTE (verified live 2026-09-22):
#   Current DNS (nameservers ns1/ns2.orawebhost.co.ke, zone edited in OraWebHost cPanel):
#     A  @   -> 185.113.249.115   (Truehost Cloud KE — currently serving a Next.js build)
#     A  www -> 185.113.249.115   (Truehost Cloud KE)
#     A  mail -> 23.153.104.141   (OraWebHost — EMAIL, DO NOT TOUCH)
#     MX 10 mail.initiativeforlegalaid.org.   (DO NOT TOUCH)
#     TXT SPF "v=spf1 a mx ip4:23.153.104.141 ip4:23.153.104.141 ~all"  (DO NOT TOUCH)
#   Rollback target for this cutover = 185.113.249.115 (both @ and www).
#
# Historical reference (first cutover, 2026-09-15):
#   Current DNS then: A @ -> 23.153.104.141, A www -> 23.153.104.141
#   (OraWebHost WordPress), nameservers ns1/ns2.orawebhost.co.ke ->
#   DNS edited in OraWebHost's panel (cPanel Zone Editor).

## STEP 0 — Pre-flight (do first)
- [ ] Confirm you can log in to https://https-initiativeforlegalaid-org-1.onrender.com/login (Free).
- [ ] Set ADMIN_BOOTSTRAP=0 in Render → Environment (done after first login).
- [ ] Confirm Render → Disks has the disk at /opt/render/project/src/data.
- [ ] Optional: back up the old WordPress site (OraWebHost export) for content reference.
- [ ] **MAIL WARNING (verified 2026-09-15): email for this domain is hosted on the OLD
      server (MX → mail.initiativeforlegalaid.org → 23.153.104.141, SPF on file).
      When cutting over, touch ONLY the `@` and `www` records.
      DO NOT delete or change: the `mail` A record, the MX record, or the TXT/SPF record —
      otherwise all @initiativeforlegalaid.org email (including info@ and the leadership
      addresses on /leadership) stops receiving.**

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
- Keep the Truehost (185.113.249.115) site active for 48 h, then cancel/migrate.
- Rollback: point both records back to A 185.113.249.115 (propagates within TTL 300).
- After 48 h stable, raise TTL back to 3600.

