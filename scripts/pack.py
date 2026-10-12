#!/usr/bin/env python3
"""Create the zip to hand to the next session.   python scripts/pack.py 2   (or 0-1)
Writes cakezz-repo_after_part_<label>.zip NEXT TO the cakezz/ folder (or into --out DIR).
Contains every file of the repo, with 'cakezz/' as the only top folder."""
import subprocess, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
label = next((x for x in sys.argv[1:] if not x.startswith("--")), "x")
out_dir = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", ".mypy_cache"}
SKIP_SUFFIX = {".pyc", ".joblib", ".zip"}

r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_repo.py"), "--write-state"])
if r.returncode:
    print("WARNING: fix the PROBLEM lines above, then run pack.py again.")
out = out_dir / f"cakezz-repo_after_part_{label}.zip"
n = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_dir() or SKIP_DIRS & set(rel.parts) or p.suffix in SKIP_SUFFIX:
            continue
        if p.name == ".env" or (p.name.startswith(".env.") and p.name != ".env.example"):
            continue  # never ship secrets
        z.write(p, Path("cakezz") / rel)
        n += 1
print(f"Wrote {out} ({n} files)")
