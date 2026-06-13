"""Shared Kaggle download helper — works WITH or WITHOUT an API token.

Two ways to get a Kaggle dataset into `dest`:

A. MANUAL (no token, anyone can do it):
   1. Open the dataset page in a browser:  https://www.kaggle.com/datasets/<slug>
   2. Click  Download  (you may need a free Kaggle login).
   3. Drop the downloaded .zip into the folder this script prints (e.g.
      dataset/_raw/rf_v2/).  Do NOT unzip it yourself — leave the .zip as-is.
   4. Re-run the same fetch command. It finds the zip, extracts it, and adapts it.

B. API (optional, for automation):
   1. kaggle.com -> Account -> 'Create New API Token' -> downloads kaggle.json
   2. Put it at  %USERPROFILE%\\.kaggle\\kaggle.json
      (or set env KAGGLE_USERNAME / KAGGLE_KEY)
   3. pip install kaggle  (already in requirements-core.txt), then re-run.

Either way the pipeline still works on mock data if you skip this entirely.
"""
from __future__ import annotations
import os, glob, zipfile


def _have_credentials() -> bool:
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return True
    cfg = os.path.join(os.path.expanduser("~"), ".kaggle", "kaggle.json")
    return os.path.exists(cfg)


def _already_extracted(dest: str) -> bool:
    """True if `dest` holds real content (anything other than a bare .zip)."""
    if not os.path.isdir(dest):
        return False
    for name in os.listdir(dest):
        if not name.lower().endswith(".zip"):
            return True
    return False


def _extract_local_zip(dest: str) -> bool:
    """If the user dropped a .zip into `dest`, extract it in place. Returns success."""
    zips = glob.glob(os.path.join(dest, "*.zip"))
    if not zips:
        return False
    zpath = zips[0]
    print(f"[kaggle] found manual download: {os.path.basename(zpath)} — extracting...")
    try:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(dest)
        print("[kaggle] extracted.")
        return True
    except Exception as e:
        print(f"[kaggle] could not extract {zpath}: {type(e).__name__}: {e}")
        return False


def _manual_instructions(slug: str, dest: str) -> None:
    url = f"https://www.kaggle.com/datasets/{slug}"
    print(f"""
[kaggle] No data and no API token for '{slug}'. Two options:

  MANUAL (no token needed — recommended):
    1. Open:     {url}
    2. Click 'Download' (free Kaggle login may be required).
    3. Move the downloaded .zip into:
         {os.path.abspath(dest)}
       (leave it zipped — do NOT extract it yourself)
    4. Re-run this exact command. It will extract + adapt automatically.

  API (optional, for automation):
    kaggle.com -> Account -> Create New API Token -> save kaggle.json to
    {os.path.join(os.path.expanduser('~'), '.kaggle', 'kaggle.json')}
    then re-run.

(The pipeline still works on mock data without any of this.)
""")


def download_dataset(slug: str, dest: str, unzip: bool = True) -> bool:
    """Ensure Kaggle dataset `slug` (owner/name) is available under `dest`.

    Resolution order:
      1. already extracted there            -> use it
      2. a manually-downloaded .zip in dest -> extract it (NO token needed)
      3. API token present                  -> download via Kaggle API
      4. otherwise                          -> print manual instructions, return False
    """
    os.makedirs(dest, exist_ok=True)

    if _already_extracted(dest):
        return True

    if _extract_local_zip(dest):
        return True

    if _have_credentials():
        try:
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi(); api.authenticate()
            print(f"[kaggle] downloading {slug} -> {dest} ...")
            api.dataset_download_files(slug, path=dest, unzip=unzip, quiet=False)
            print("[kaggle] done.")
            return True
        except Exception as e:
            print(f"[kaggle] API download failed: {type(e).__name__}: {e}")
            _manual_instructions(slug, dest)
            return False

    _manual_instructions(slug, dest)
    return False
