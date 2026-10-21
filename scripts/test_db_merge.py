"""Offline checks for the three-way DB merge (no network). Run: .venv/bin/python scripts/test_db_merge.py"""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("PROD_ADMIN_USER", "test-user")
os.environ.setdefault("PROD_ADMIN_PASSWORD", "test-pass")

spec = importlib.util.spec_from_file_location(
    "spc", Path(__file__).resolve().parent / "sync_prod_content.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

tmp = Path(tempfile.mkdtemp())
counter = [0]


def mkdb(data):
    counter[0] += 1
    path = tmp / ("merge-%d.db" % counter[0])
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE site_data (id INTEGER PRIMARY KEY, data JSON)")
    conn.execute("INSERT INTO site_data (id, data) VALUES (1, ?)", (json.dumps(data),))
    conn.commit()
    conn.close()
    return path


failures = []


def check(name, condition, detail=""):
    print(("PASS" if condition else "FAIL"), name, detail)
    if not condition:
        failures.append(name)


# 1. Production wins a conflict; private keys stay local.
p1 = mkdb({"tagline": "A", "admin_users": ["local-admin"]})
changed, up, skipped = mod.merge_local_db(
    {"tagline": "B (panel edit)"}, {"tagline": "A"}, db_path=p1
)
after = mod.read_local_db(p1)
check("T1-conflict-prod-wins", after.get("tagline") == "B (panel edit)", str(after.get("tagline")))
check("T1-private-stays-local", after.get("admin_users") == ["local-admin"])
check("T1-push-lists-clean", up == [] and skipped == [], "%r %r" % (up, skipped))

# 2. Local-only addition is reported for push-up (and kept locally).
p2 = mkdb({"tagline": "B"})
cur = mod.read_local_db(p2)
cur["local_note"] = "hello"
mod.write_local_db(cur, p2)
changed, up, skipped = mod.merge_local_db({"tagline": "B"}, {"tagline": "B"}, db_path=p2)
check("T2-local-only-reported", up == ["local_note"], str(up))
check("T2-local-only-kept", mod.read_local_db(p2).get("local_note") == "hello")

# 3. Production deletion of an untouched key removes it locally.
p3 = mkdb({"tagline": "B", "old_key": "v"})
changed, up, skipped = mod.merge_local_db(
    {"tagline": "B"}, {"tagline": "B", "old_key": "v"}, db_path=p3
)
check("T3-untouched-delete-removed", "old_key" not in mod.read_local_db(p3))

# 4. Production deletion of a locally-edited key keeps the local value + flag.
p4 = mkdb({"tagline": "B", "old_key": "LOCAL EDIT"})
changed, up, skipped = mod.merge_local_db(
    {"tagline": "B"}, {"tagline": "B", "old_key": "v"}, db_path=p4
)
after4 = mod.read_local_db(p4)
check("T4-edited-delete-kept", after4.get("old_key") == "LOCAL EDIT" and skipped == ["old_key"])

# 5. Identical state is a quiet no-op.
p5 = mkdb({"tagline": "B"})
changed, up, skipped = mod.merge_local_db({"tagline": "B"}, {"tagline": "B"}, db_path=p5)
check("T5-noop", changed is False and up == [] and skipped == [])

if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("ALL-MERGE-TESTS-PASS")
