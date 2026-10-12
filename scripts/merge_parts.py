#!/usr/bin/env python3
"""Merge parts that were built in parallel on different accounts.

  python scripts/merge_parts.py merged.zip base=after_part_0.zip 1=a.zip 2=b.zip 3=c.zip 4=d.zip

Starts from the base zip, then for each N=zip it takes ONLY the paths that Part N owns
(see scripts/ownership.json) plus state/part-N.md. Result: one zip with everything."""
import json, sys, zipfile
from pathlib import Path

CFG = json.loads((Path(__file__).resolve().parent / "ownership.json").read_text())


def load(path):
    with zipfile.ZipFile(path) as z:
        files = {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}
    tops = {f.split("/")[0] for f in files}
    if tops == {"cakezz"}:
        files = {f.split("/", 1)[1]: b for f, b in files.items()}
    else:
        sys.exit(f"{path}: expected a single top folder 'cakezz/'")
    return files


def owned(part, rel):
    if any(rel.startswith(x) for x in CFG["owns_exclude"].get(part, [])):
        return False
    return rel == f"state/part-{part}.md" or any(rel == o or rel.startswith(o) for o in CFG["owns"][part] if o is not None)


def main():
    out, *items = sys.argv[1:]
    args = dict(i.split("=", 1) for i in items)
    merged = load(args.pop("base"))
    for part, path in sorted(args.items()):
        if part not in CFG["owns"] or part == "7":
            sys.exit(f"Part {part}: not mergeable (use 0-6 only; Part 7 runs alone on the merged repo)")
        src = load(path)
        for rel in [r for r in merged if owned(part, r)]:
            del merged[rel]
        taken = {r: b for r, b in src.items() if owned(part, r)}
        merged.update(taken)
        print(f"Part {part}: took {len(taken)} files from {path}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, b in sorted(merged.items()):
            z.writestr(f"cakezz/{rel}", b)
    print(f"Wrote {out}. Unzip it and run: python cakezz/scripts/check_repo.py --write-state")


main()
