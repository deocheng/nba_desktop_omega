import os, zipfile

ROOT = r"C:\autopick\AutoPick\nba_data\nba_desktop\nba_desktop_omega"
OUT = os.path.join(ROOT, "nba_desktop_omega_mac_migrate_2026-07-13.zip")

# explicit deny set -- CODE pkg must NOT carry data/venv/secrets
SKIP_DIRS = {'.venv', 'nba_csv', '.git', '__pycache__', 'node_modules', 'dist', 'build',
             '.pytest_cache', '.cache', '.pdf_extract', 'scratch_archive'}
SKIP_FILES = {'.env', 'replay_verify.json', 'nba_csv.zip', 'nba_csv_2026-07-13.zip',
              'nba_desktop_omega_mac_migrate_2026-07-13.zip', 'db.sqlite3', 'nba_schema_only.sql.bak'}
SKIP_EXT = {'.pyc', '.log', '.tmp', '.bak', '.swp', '.pyo'}

def allowed(rel):
    parts = rel.split(os.sep)
    for p in parts:
        if p in SKIP_DIRS:
            return False
    # only keep .workbuddy/memory, drop the rest of .workbuddy (teams/agents/tmp)
    if parts[0] == '.workbuddy' and (len(parts) < 2 or parts[1] != 'memory'):
        return False
    if parts[-1] in SKIP_FILES:
        return False
    if os.path.splitext(parts[-1])[1].lower() in SKIP_EXT:
        return False
    return True

entries = 0
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as z:
    for dp, dn, fn in os.walk(ROOT):
        # prune skip dirs so walk doesn't descend
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        # inside .workbuddy, keep only memory/
        if os.path.basename(dp) == '.workbuddy':
            dn[:] = [d for d in dn if d in ('memory',)]
        for f in fn:
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, ROOT)
            if allowed(rel):
                z.write(full, rel)
                entries += 1

print("CODE PKG entries:", entries)
print("CODE PKG size MB: %.1f" % (os.path.getsize(OUT)/1e6))
