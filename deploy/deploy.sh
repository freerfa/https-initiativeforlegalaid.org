#!/usr/bin/env bash
# Initiative for Legal Aid — Ubuntu 24.04 production deploy (Option A: replace WordPress)
# Run as root on a FRESH VPS. Usage: DOMAIN=initiativeforlegalaid.org ADMIN_EMAIL=you@example.com bash deploy.sh
set -euo pipefail
DOMAIN="${DOMAIN:-initiativeforlegalaid.org}"
ADMIN_EMAIL="${ADMIN_EMAIL:?set ADMIN_EMAIL env var}"
APP_DIR="/opt/ila"
APP_USER="ila"

echo "==> 1/7 apt + firewall"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx certbot python3-certbot-nginx git ufw > /dev/null
ufw allow OpenSSH >/dev/null; ufw allow 80,443/tcp >/dev/null; ufw --force enable >/dev/null

echo "==> 2/7 app user + code"
id -u "$APP_USER" &>/dev/null || useradd -r -m -s /bin/bash "$APP_USER"
if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull --ff-only; else git clone -b main https://github.com/freerfa/https-initiativeforlegalaid.org-.git "$APP_DIR"; fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> 3/7 venv + deps"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" -r "$APP_DIR/requirements-prod.txt"

echo "==> 4/7 .env (YOU MUST EDIT)"
if [ ! -f "$APP_DIR/.env" ]; then
  SECRET=$(python3 -c "import secrets;print(secrets.token_hex(32))")
  cat > "$APP_DIR/.env" <<EOF
SECRET_KEY=$SECRET
ADMIN_USERNAME=Free
ADMIN_PASSWORD=CHANGE-ME-NOW-min-12-chars
ADMIN_BOOTSTRAP=1
FLASK_ENV=production
PORT=8000
EOF
  chmod 600 "$APP_DIR/.env"; chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  echo "    Created $APP_DIR/.env with random SECRET_KEY — EDIT ADMIN_PASSWORD, keep ADMIN_BOOTSTRAP=1 for first boot."
else echo "    $APP_DIR/.env exists — leaving untouched."; fi
mkdir -p "$APP_DIR/static/uploads"; chown -R "$APP_USER:$APP_USER" "$APP_DIR/static/uploads"

echo "==> 5/7 systemd service"
cp "$APP_DIR/deploy/ila.service" /etc/systemd/system/ila.service
systemctl daemon-reload; systemctl enable --now ila
sleep 3; systemctl is-active --quiet ila && echo "    ila.service ACTIVE" || { journalctl -u ila -n 30 --no-pager; exit 1; }

echo "==> 6/7 nginx + HTTPS"
sed "s/__DOMAIN__/$DOMAIN/g" "$APP_DIR/deploy/nginx-ila.conf" > /etc/nginx/sites-available/ila
ln -sf /etc/nginx/sites-available/ila /etc/nginx/sites-enabled/ila
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --non-interactive --agree-tos -m "$ADMIN_EMAIL" --redirect

echo "==> 7/7 first-boot admin + lock down"
echo "    Log in ONCE at https://$DOMAIN/login with Free / your ADMIN_PASSWORD (bootstrap creates it)."
echo "    THEN: set ADMIN_BOOTSTRAP=0 in $APP_DIR/.env && systemctl restart ila"
echo "    Backup live DB: cp $APP_DIR/site.db /root/ila-site.db.\$(date +%F).bak"
echo "DONE. Site should be live at https://$DOMAIN"
