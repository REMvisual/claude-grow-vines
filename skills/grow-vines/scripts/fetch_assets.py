#!/usr/bin/env python3
"""fetch_assets.py -- download the vendored bark PBR sets (one-time setup).

The generator textures its stems from three ambientCG bark sets (CC0 --
https://ambientcg.com/ -- free for any use, no attribution required). They are
not committed to the repo to keep clones small; this script pulls them straight
from ambientcg.com into scripts/assets/bark/.

Usage (plain Python 3, no Blender needed):
    python scripts/fetch_assets.py

Idempotent: sets that already have their four maps are skipped.
"""
import io
import os
import sys
import zipfile
import urllib.request

SETS = ["Bark002", "Bark006", "Bark012"]
MAPS = ["Color", "NormalGL", "Roughness", "Displacement"]
URL = "https://ambientcg.com/get?file={set}_2K-JPG.zip"
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "bark")


def have_all(set_dir, s):
    return all(os.path.isfile(os.path.join(set_dir, f"{s}_2K-JPG_{m}.jpg"))
               for m in MAPS)


def fetch(s):
    set_dir = os.path.join(DEST, s.lower())
    if have_all(set_dir, s):
        print(f"[fetch] {s}: already present, skipping")
        return True
    os.makedirs(set_dir, exist_ok=True)
    url = URL.format(set=s)
    print(f"[fetch] {s}: downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "claude-grow-vines-setup"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception as e:
        print(f"[fetch] {s}: download failed: {e}")
        return False
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        print(f"[fetch] {s}: response was not a zip (ambientCG layout change?)")
        return False
    n = 0
    for name in zf.namelist():
        base = os.path.basename(name)
        if any(base == f"{s}_2K-JPG_{m}.jpg" for m in MAPS):
            with open(os.path.join(set_dir, base), "wb") as f:
                f.write(zf.read(name))
            n += 1
    print(f"[fetch] {s}: extracted {n}/{len(MAPS)} maps -> {set_dir}")
    return n == len(MAPS)


def main():
    ok = all([fetch(s) for s in SETS])
    if ok:
        print("[fetch] all bark sets ready")
        return 0
    print("[fetch] some sets failed -- re-run, or download the *_2K-JPG.zip files "
          "manually from ambientcg.com and unzip the four .jpg maps into "
          "scripts/assets/bark/<setname>/")
    return 1


if __name__ == "__main__":
    sys.exit(main())
