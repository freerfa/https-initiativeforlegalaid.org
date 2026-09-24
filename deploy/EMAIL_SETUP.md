# Email for the ILA website

Status: **built and live** (2026-09-24). The site now has a working contact form
with an office inbox, and optional email notifications.

---

## 1. What the site does today

| Capability | Where | Works without any email provider? |
| --- | --- | --- |
| Public contact form | `https://initiative4legalaid.org/contact` | Yes |
| Every enquiry saved to the database | `contact_messages` table | Yes |
| Office inbox with unread badge | `/admin/messages` (admin login) | Yes |
| Mark read / unread, delete, reply-by-email | `/admin/messages` | Yes |
| Spam brake (5 messages per IP per hour) | `CONTACT_RATE_LIMIT` | Yes |
| Honeypot anti-bot field | contact form | Yes |
| **Copy of each enquiry emailed out** | mail API | **No — needs a provider key** |

So the form is never "dead": an enquiry is written to the database **first**, and
email delivery is attempted afterwards. If the provider is down or unconfigured,
the message is still in the office inbox and the visitor is told it was received.

From the admin inbox you can always reply — every message has a
**Reply by email** link that opens the visitor's address with the subject
pre-filled.

---

## 2. Why not plain SMTP?

The site runs on **Render**, which blocks outbound SMTP on ports 25, 465 and 587
to prevent spam. A normal `smtplib`/SMTP login to Hostinger mail therefore cannot
work from the Render service.

Email is instead sent over an **HTTPS API on port 443** (`urllib.request`, in
`send_notification_email()` in `app.py`). No extra Python package is needed.
`MAIL_API_URL` defaults to Resend's endpoint, so a different provider can be
swapped in by changing that one variable.

The Hostinger mailboxes at `initiative4legalaid.org` are **unaffected**: the MX,
SPF and DMARC records stay exactly as they are. Reading and sending mail from
Outlook/Thunderbird/webmail uses Hostinger directly and has nothing to do with
Render. This integration only *sends a notification* from the website.

---

## 3. Turning notifications on (15 minutes, free tier)

**Step 1 — create a Resend account.** Sign up at <https://resend.com> with the
office address, then **Domains → Add Domain → `initiative4legalaid.org`**.

**Step 2 — add the DNS records Resend shows you** in Hostinger hPanel →
Domains → DNS / Nameservers. Resend gives you a `TXT` (SPF-style verification),
a `MX` record for a `send.` subdomain, and a `TXT` DKIM record. These are
**additive** — do not delete or edit the existing Hostinger mail records
(the current `MX` on the root domain, the existing SPF `TXT`, DMARC). Then click
**Verify** in Resend; it usually turns green within minutes.

> Using a `send.initiative4legalaid.org` subdomain for the sending MX keeps
> website notifications completely separate from the Hostinger mailboxes, which
> is why both can coexist safely.

**Step 3 — create an API key.** Resend → **API Keys → Create** (permission
"Sending access"). Copy the `re_...` value.

**Step 4 — set the environment variables in Render.** Dashboard → the `ila`
service → **Environment**:

```
RESEND_API_KEY = re_xxxxxxxxxxxxxxxxxxxxxx
MAIL_FROM      = ILA Website <website@initiative4legalaid.org>
MAIL_TO        = legalaid4southsudan@gmail.com
```

`MAIL_TO` accepts several comma-separated addresses, e.g.
`legalaid4southsudan@gmail.com,info@initiative4legalaid.org`.
`MAIL_FROM` must be on the domain verified in Step 2.

**Step 5 — save and redeploy.** Render restarts the service automatically.

**Step 6 — test.** Open `/contact`, send a test message, then check
`/admin/messages`: the entry's `email:` status must read **sent**, and the
`MAIL_TO` inbox should have the copy. If it reads `not_configured`, a variable is
missing; if `failed: ...`, the reason is printed in the same line.

---

## 4. Verifying from the command line

```bash
# the page and form are live
curl -s -o /dev/null -w '%{http_code}\n' https://initiative4legalaid.org/contact

# the mail DNS is still intact (must NOT be empty)
dig +short MX initiative4legalaid.org
dig +short TXT initiative4legalaid.org

# if you added the Resend subdomain records, this should return a hostname
dig +short MX send.initiative4legalaid.org
```

---

## 5. Notes and limitations

- **Messages live on the Render disk.** `DATA_DIR=/opt/render/project/src/data`
  is a persistent 1 GB disk, so the inbox survives restarts and redeploys. It is
  still a single disk: `/admin/database → Export` is the backup path.
- **The inbox is admin-only.** `/admin/messages` requires the admin login, and
  every state change is a `POST` protected by CSRF tokens.
- **No file uploads on the form, by design.** The page asks visitors not to send
  confidential case details in a first message.
- **Notifications are one-way.** Replies are sent from the office mailbox
  (Hostinger webmail/Outlook), not from the website.
- **Reputation.** A brand-new sending domain can land in spam at first. Resend's
  DKIM/SPF records fix the authentication side; if messages still land in spam,
  tell partners to mark them "not spam" once.
