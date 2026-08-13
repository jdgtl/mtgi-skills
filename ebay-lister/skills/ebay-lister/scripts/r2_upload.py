#!/usr/bin/env python3
"""Stage local product photos to Cloudflare R2 and return public URLs.

eBay copies self-hosted images to eBay Picture Services when the listing
publishes, so R2 is a staging hop, not permanent infrastructure the live
listing depends on. The URLs only have to resolve at publish time.

Filename convention (already in use in work/product-images/):

    <product-slug>-<unit>-<image#>.<ext>
    corsair-64gb-ram-01-1.png   -> group "corsair-64gb-ram-01", image 1

One group == one physical unit == one listing. Image 1 is the eBay gallery
photo, so ordering is load-bearing.

CLI:
    python r2_upload.py scan  <folder>
    python r2_upload.py stage <folder> --group corsair-64gb-ram-01 --sku MTGI-XXX
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import credentials

# eBay's own ceilings. Enforced here so a listing fails locally, not at publish.
MAX_IMAGES_PER_LISTING = 24
MAX_FILE_SIZE_BYTES = 12 * 1024 * 1024
MAX_PIXELS_PER_SIDE = 9000

# eBay recommends 1600px on the longest side. Phone photos land around
# 4032x3024 at 10-15MB, which is both over the file cap and pointless detail
# for a listing page -- so optimize by default rather than rejecting them.
OPTIMIZE_LONGEST_SIDE = 1600
OPTIMIZE_JPEG_QUALITY = 90

CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# eBay accepts JPEG, PNG, GIF, BMP, TIFF for self-hosted images. WebP is NOT
# accepted -- flag it at scan time rather than letting publish fail.
EBAY_SAFE_TYPES = {"image/jpeg", "image/png", "image/gif"}

GROUP_RE = re.compile(r"^(?P<group>.+)-(?P<index>\d+)$")

WRANGLER_TIMEOUT_S = 180

# Cloudflare answers the default `Python-urllib/x.y` User-Agent with 403 on this
# zone, so an unset UA makes every verification a false negative -- the upload
# is fine, the URL is fine, and the skill refuses to publish anyway. eBay's
# fetcher sends its own UA and is unaffected; this is purely about the check.
VERIFY_USER_AGENT = "ebay-lister/0.1 (+https://github.com/jdgtl/mtgi-skills)"


class R2Error(RuntimeError):
    """Staging failed in a way the operator has to resolve."""


def _bucket() -> str:
    return credentials.get("r2_bucket") or "mtgi"


def _public_base() -> str:
    return (credentials.get("r2_public_base") or "").rstrip("/")


def _prefix() -> str:
    return (credentials.get("r2_prefix") or "listings").strip("/")


def scan(folder: str | Path) -> dict:
    """Group images in a flat folder by <slug>-<unit>, ordered by image number."""
    path = Path(folder).expanduser()
    if not path.is_dir():
        raise R2Error(f"Not a folder: {path}")

    groups: dict[str, list[tuple[int, Path]]] = {}
    skipped: list[dict] = []

    for entry in sorted(path.iterdir()):
        if not entry.is_file() or entry.name.startswith("."):
            continue
        content_type = CONTENT_TYPES.get(entry.suffix.lower())
        if not content_type:
            skipped.append({"file": entry.name, "reason": "unsupported extension"})
            continue
        match = GROUP_RE.match(entry.stem)
        if not match:
            skipped.append({"file": entry.name, "reason": "does not match <group>-<index>"})
            continue
        groups.setdefault(match.group("group"), []).append((int(match.group("index")), entry))

    out = {}
    for group, items in sorted(groups.items()):
        items.sort(key=lambda pair: pair[0])
        files = []
        for index, entry in items:
            content_type = CONTENT_TYPES[entry.suffix.lower()]
            warnings = []
            size = entry.stat().st_size
            # Oversized and WebP are both fixed by the optimize pass at stage
            # time, so these are informational, not blocking.
            if size > MAX_FILE_SIZE_BYTES:
                warnings.append(
                    f"{size / 1024 / 1024:.1f}MB exceeds eBay's "
                    f"{MAX_FILE_SIZE_BYTES // 1024 // 1024}MB cap -- will be optimized on stage"
                )
            if content_type not in EBAY_SAFE_TYPES:
                warnings.append(
                    f"eBay does not accept {content_type} for self-hosted images "
                    f"-- will be converted to JPEG on stage"
                )
            files.append(
                {
                    "index": index,
                    "path": str(entry),
                    "name": entry.name,
                    "content_type": content_type,
                    "size_bytes": size,
                    "warnings": warnings,
                }
            )
        if len(files) > MAX_IMAGES_PER_LISTING:
            files = files[:MAX_IMAGES_PER_LISTING]
        out[group] = {"count": len(files), "files": files, "gallery_image": files[0]["name"] if files else None}

    return {"folder": str(path), "groups": out, "skipped": skipped}


def _optimize(source: Path, dest_dir: Path) -> tuple[Path, str, dict]:
    """Downscale to eBay's recommended size and convert to JPEG via `sips`.

    `sips` ships with macOS, so this needs no third-party imaging library.
    Returns (path, content_type, stats). Falls back to the original file if
    `sips` is unavailable or fails -- the caller still enforces the hard caps.
    """
    original_size = source.stat().st_size
    if not shutil.which("sips"):
        return source, CONTENT_TYPES[source.suffix.lower()], {
            "optimized": False,
            "reason": "sips not available (non-macOS host)",
            "bytes": original_size,
        }

    dest = dest_dir / f"{source.stem}.jpg"
    cmd = [
        "sips",
        "-Z", str(OPTIMIZE_LONGEST_SIDE),
        "-s", "format", "jpeg",
        "-s", "formatOptions", str(OPTIMIZE_JPEG_QUALITY),
        str(source),
        "--out", str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not dest.exists():
        return source, CONTENT_TYPES[source.suffix.lower()], {
            "optimized": False,
            "reason": (proc.stderr or "sips failed").strip()[:200],
            "bytes": original_size,
        }

    new_size = dest.stat().st_size
    return dest, "image/jpeg", {
        "optimized": True,
        "bytes": new_size,
        "original_bytes": original_size,
        "saved_pct": round((1 - new_size / original_size) * 100) if original_size else 0,
    }


def _wrangler_put(key: str, file_path: Path, content_type: str) -> None:
    """Upload one object via wrangler.

    `--remote` is REQUIRED. Wrangler v4 made every `r2 object` command default
    to local mode, so without it the file lands in a local simulation directory,
    the command still exits 0, and every eBay image URL 404s at publish.
    """
    cmd = [
        "npx",
        "--yes",
        "wrangler@latest",
        "r2",
        "object",
        "put",
        f"{_bucket()}/{key}",
        f"--file={file_path}",
        f"--content-type={content_type}",
        "--remote",
    ]
    # A Cloudflare login that can reach more than one account makes wrangler
    # bail out in non-interactive mode rather than pick one, so pin the account.
    env = os.environ.copy()
    account_id = credentials.get("cloudflare_account_id")
    if account_id:
        env["CLOUDFLARE_ACCOUNT_ID"] = account_id

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=WRANGLER_TIMEOUT_S, env=env
        )
    except FileNotFoundError as e:
        raise R2Error("`npx` not found. Node.js is required to stage images to R2.") from e
    except subprocess.TimeoutExpired as e:
        raise R2Error(f"wrangler timed out after {WRANGLER_TIMEOUT_S}s uploading {key}") from e

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if "More than one account" in detail:
            raise R2Error(
                "wrangler could not choose between your Cloudflare accounts.\n"
                "Set the cloudflare_account_id credential to the one owning the bucket:\n"
                "  python3 credentials.py set cloudflare_account_id <account-id>"
            )
        if "authentication" in detail.lower() or "10000" in detail:
            raise R2Error(
                f"wrangler could not authenticate to Cloudflare.\n"
                f"Set CLOUDFLARE_API_TOKEN (with R2 write scope) or run `npx wrangler login`.\n\n{detail[:600]}"
            )
        raise R2Error(f"wrangler failed on {key}:\n{detail[:800]}")


def _verify_public(url: str, attempts: int = 5) -> dict:
    """HEAD the public URL. eBay fetches these server-side -- a 403/404 here
    means the listing would publish with broken images.

    Retries with backoff: an object is not always visible on the custom domain
    the instant `wrangler put` returns, so a single immediate check reports a
    false 404 on a perfectly good upload.
    """
    status, error = 0, None
    for attempt in range(attempts):
        if attempt:
            time.sleep(attempt)  # 1s, 2s, 3s, 4s
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": VERIFY_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                if 200 <= status < 300:
                    return {"url": url, "status": status, "ok": True, "attempts": attempt + 1}
        except urllib.error.HTTPError as e:
            status = e.code
        except urllib.error.URLError as e:
            status, error = 0, str(e.reason)
    out = {"url": url, "status": status, "ok": False, "attempts": attempts}
    if error:
        out["error"] = error
    return out


def stage(
    folder: str | Path, group: str, sku: str, verify: bool = True, optimize: bool = True
) -> dict:
    """Upload one group's images to R2 and return ordered public URLs.

    With optimize=True (the default) each photo is downscaled to eBay's
    recommended 1600px and converted to JPEG first, which takes typical phone
    photos from 10-15MB to well under the 12MB cap.
    """
    public_base = _public_base()
    if not public_base:
        raise R2Error("R2 public base URL is not configured. Run /ebay-setup.")

    scanned = scan(folder)
    entry = scanned["groups"].get(group)
    if not entry:
        raise R2Error(
            f"No image group '{group}' in {folder}. Available: {sorted(scanned['groups'])}"
        )
    if not entry["files"]:
        raise R2Error(f"Image group '{group}' has no usable files.")

    urls, checks, optimizations = [], [], []
    with tempfile.TemporaryDirectory(prefix="ebay-lister-") as tmp:
        tmp_dir = Path(tmp)
        for image in entry["files"]:
            source = Path(image["path"])
            content_type = image["content_type"]

            if optimize:
                source, content_type, stats = _optimize(source, tmp_dir)
                stats["name"] = image["name"]
                optimizations.append(stats)

            size = source.stat().st_size
            if size > MAX_FILE_SIZE_BYTES:
                raise R2Error(
                    f"{image['name']} is {size / 1024 / 1024:.1f}MB after processing; "
                    f"eBay's cap is {MAX_FILE_SIZE_BYTES // 1024 // 1024}MB. "
                    f"Shrink it manually or re-run without --no-optimize."
                )
            if content_type not in EBAY_SAFE_TYPES:
                raise R2Error(
                    f"{image['name']} is {content_type}; eBay does not accept that "
                    f"format for self-hosted images. Convert it to JPEG or PNG."
                )

            # Content hash in the key, not just the index. The R2 custom domain
            # sits behind Cloudflare's edge cache, so re-staging a corrected
            # photo at the same key can serve eBay the stale cached image --
            # silently, since the URL still returns 200. Different bytes now
            # mean a different key, which no cache can confuse.
            digest = hashlib.sha256(source.read_bytes()).hexdigest()[:10]
            key = f"{_prefix()}/{sku}/{image['index']:02d}-{digest}{source.suffix.lower()}"
            _wrangler_put(key, source, content_type)
            url = f"{public_base}/{key}"
            urls.append(url)
            if verify:
                checks.append(_verify_public(url))

    failed = [c for c in checks if not c["ok"]]
    return {
        "group": group,
        "sku": sku,
        "bucket": _bucket(),
        "imageUrls": urls,
        "gallery_image": urls[0] if urls else None,
        "optimizations": optimizations,
        "verified": not failed,
        "failed_checks": failed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage listing images to Cloudflare R2")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("folder")
    st = sub.add_parser("stage")
    st.add_argument("folder")
    st.add_argument("--group", required=True)
    st.add_argument("--sku", required=True)
    st.add_argument("--no-verify", action="store_true")
    st.add_argument(
        "--no-optimize",
        action="store_true",
        help="upload originals as-is instead of downscaling to 1600px JPEG",
    )
    args = parser.parse_args(argv)

    try:
        if args.cmd == "scan":
            print(json.dumps(scan(args.folder), indent=2))
        else:
            result = stage(
                args.folder,
                args.group,
                args.sku,
                verify=not args.no_verify,
                optimize=not args.no_optimize,
            )
            print(json.dumps(result, indent=2))
            if not result["verified"]:
                return 1
    except R2Error as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
