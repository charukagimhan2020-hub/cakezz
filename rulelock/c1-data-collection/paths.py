"""Puts the four component folders on sys.path (their folder names have a hyphen, so they are not importable packages).
Import this module first: `import paths`. Layout in the repo and in the Docker image (/app):
  c1-data-collection  c2-rule-engine  c3-anomaly-detection  c4-enforcement-engine
c1 comes FIRST so its own names (app, config, db, ...) win over the optional app.py wrappers of c2, c3 and c4."""
import sys
from pathlib import Path

C1 = Path(__file__).resolve().parent
RULELOCK = C1.parent
COMPONENTS = ("c2-rule-engine", "c3-anomaly-detection", "c4-enforcement-engine")


def setup():
    for name in COMPONENTS:
        folder = str(RULELOCK / name)
        if folder not in sys.path:
            sys.path.append(folder)
    if str(C1) not in sys.path:
        sys.path.insert(0, str(C1))


setup()
