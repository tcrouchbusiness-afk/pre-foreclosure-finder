"""Download the Property Appraiser's free bulk files and extract each into data/pa/<key>/.

Usage: python scripts/download_pa.py            (skips datasets already present)
       python scripts/download_pa.py --force    (re-download everything)

Sizes for Martin County (2026-10): master 64 MB, transfers 95 MB, improvement 32 MB, others ~10 MB.
"""
import glob, io, os, shutil, sys, time, urllib.request, zipfile
from config import CFG, ROOT

PA = CFG["property_appraiser"]
OUT = os.path.join(ROOT, "data", "pa")


def main():
    force = "--force" in sys.argv
    for key, ds in PA["datasets"].items():
        dest = os.path.join(OUT, key)
        if not force and glob.glob(os.path.join(dest, "*.*")):
            print(f"{key}: present, skipping")
            continue
        url = PA["download_url"].format(id=ds)
        print(f"{key}: downloading {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (pre-foreclosure-finder)"})
        data = urllib.request.urlopen(req, timeout=600).read()
        if not data.startswith(b"PK"):
            sys.exit(f"{key}: not a zip ({len(data)} bytes). Check the dataset id on {PA['downloads_page']}")
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest)
        zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
        print(f"{key}: {len(data) / 1e6:.1f} MB -> {', '.join(os.listdir(dest))}")
        time.sleep(2)  # be polite to the county server


if __name__ == "__main__":
    main()
