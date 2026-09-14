# DNS cutover (Option A) — do this LAST, after the VPS serves the Flask app
# Current: A @ → 23.153.104.141, A www → 23.153.104.141 (OraWebHost WordPress)

1. Lower TTL to 300s at least 24h before (registrar/DNS panel, both A records).
2. On the VPS, verify locally first:
     curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
     curl -sk -o /dev/null -w '%{http_code}\n' -H 'Host: initiativeforlegalaid.org' https://127.0.0.1/
3. Change BOTH records to the new VPS IP:
     A  @    <NEW-VPS-IP>   TTL 300
     A  www  <NEW-VPS-IP>   TTL 300
4. Wait for propagation, then verify worldwide:
     dig +short initiativeforlegalaid.org
     curl -s -o /dev/null -w 'root:%{http_code} final:%{url_effective}\n' https://initiativeforlegalaid.org/
     curl -s -o /dev/null -w 'www:%{http_code} final:%{url_effective}\n' https://www.initiativeforlegalaid.org/
5. Raise TTL back to 3600+. Keep the old OraWebHost site 48h, then cancel.
6. Rollback (if needed): point both A records back to 23.153.104.141.
