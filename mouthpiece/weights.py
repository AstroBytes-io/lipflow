"""Download the shared model weights: resumable (.part + HTTP Range), retried, disk-checked, SHA-256 verified.

Standard library only, so it also runs as a plain script before any dependency is installed:
    python3 mouthpiece/weights.py models            # the weights into ./models
    python3 mouthpiece/weights.py --samples samples # the public-domain test clips

The weights are the Auto-AVSR LRS3 models (non-commercial research use). They are fetched from their
public mirrors on first run and are not redistributed with Mouthpiece.
"""
from __future__ import annotations

import hashlib
import http.client
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

HF = "https://huggingface.co"
# (path under the models dir, url, sha256, bytes)
FILES = [
    ("vsr/model.json", f"{HF}/Amanvir/LRS3_V_WER19.1/resolve/main/model.json",
     "e062e8c58579f54cb51087e639e674781189809905db4162efe0fe1325356d4f", 5512),
    ("vsr/model.pth", f"{HF}/Amanvir/LRS3_V_WER19.1/resolve/main/model.pth",
     "e740cef369abeabd0ba2c18e37a0661342e1d94d432d6caa77755a11821d8fe3", 1001908942),
    ("lm/model.json", f"{HF}/Amanvir/lm_en_subword/resolve/main/model.json",
     "6e2d2004e4066af3e5a3d74c53b0d648fd53904da07178671d1cbe28a206d548", 951),
    ("lm/model.pth", f"{HF}/Amanvir/lm_en_subword/resolve/main/model.pth",
     "c75aa39020dec98f432c8689b145d3f4cc407d4daa90a0c64202386c34f83c18", 215076928),
    ("lm/unigram5000.model", "https://github.com/mpc001/auto_avsr/raw/main/spm/unigram/unigram5000.model",
     "2c1d648ccf5fdce6612ecbea2ffbd1cab5aabc90458781186175c3911c4bdb1e", 327113),
    ("face_landmarker.task", "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/"
     "float16/1/face_landmarker.task",
     "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff", 3758596),
]
TOTAL = sum(f[3] for f in FILES)

_C = "https://upload.wikimedia.org/wikipedia/commons/transcoded"
SAMPLES = [  # public-domain White House weekly addresses (Wikimedia Commons), used by tests/test_pipeline.py
    ("2016-03-12.mov", f"{_C}/c/ce/2016-03-12_President_Obama%27s_Weekly_Address.webm/"
     "2016-03-12_President_Obama%27s_Weekly_Address.webm.360p.mpeg4.mov", None, 0),
    ("2017-01-07.mov", f"{_C}/2/29/2017-01-07_President_Obama%27s_Weekly_Address.webm/"
     "2017-01-07_President_Obama%27s_Weekly_Address.webm.360p.mpeg4.mov", None, 0),
]

CHUNK = 1 << 20


class DownloadError(Exception):
    """Message is meant for people: shown as-is in the app."""


def missing(root: str, files=FILES) -> list:
    """Entries not present at the right size. Cheap (no hashing), so it runs on every launch."""
    out = []
    for rel, url, sha, size in files:
        p = os.path.join(root, rel)
        if not os.path.isfile(p) or (size and os.path.getsize(p) != size):
            out.append((rel, url, sha, size))
    return out


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def corrupt(root: str, files=FILES) -> list:
    """Entries whose file fails its pinned hash (slow: reads ~1.2 GB). Use after a load fails."""
    return [e for e in files if e[2] and os.path.isfile(os.path.join(root, e[0]))
            and sha256(os.path.join(root, e[0])) != e[2]]


def _have(path):
    return os.path.getsize(path) if os.path.exists(path) else 0


def fetch(url: str, dest: str, sha: "str | None" = None, size: int = 0, progress=None,
          retries: int = 4, backoff: float = 2.0, timeout: float = 30):
    """Download url to dest via dest.part, resuming with a Range request. progress(bytes_this_file)."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"
    for attempt in range(retries + 1):
        try:
            _get(url, part, size, progress, timeout)
            break
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429 or attempt == retries:
                raise DownloadError(f"The download server refused {os.path.basename(dest)} (HTTP {e.code}). "
                                    "Try again later.") from e
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:  # offline, DNS, reset, timeout
            if attempt == retries:
                raise DownloadError("Couldn't reach the download server. Check your internet connection "
                                    "and try again; the download picks up where it stopped.") from e
        time.sleep(backoff * 2 ** attempt)
    if sha and sha256(part) != sha:
        os.remove(part)  # a resumed file with a bad hash can't be repaired, start this one over
        raise DownloadError(f"{os.path.basename(dest)} arrived damaged (checksum mismatch). Try again.")
    os.replace(part, dest)


def _get(url, part, size, progress, timeout):
    have = _have(part)
    if size and have == size:
        return
    if size and have > size:  # stale or wrong partial file
        os.remove(part)
        have = 0
    req = urllib.request.Request(url, headers={"User-Agent": "Mouthpiece", **({"Range": f"bytes={have}-"} if have else {})})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:  # nothing left to fetch: the .part is complete (hash decides)
            return
        raise
    with r:
        mode = "ab" if have and r.status == 206 else "wb"  # 200 = server ignored Range, start over
        done = have if mode == "ab" else 0
        expect = int(r.headers.get("Content-Length") or 0)
        got = 0
        with open(part, mode) as f:
            if progress:
                progress(done)
            while True:
                buf = r.read(CHUNK)
                if not buf:
                    break
                f.write(buf)
                done += len(buf)
                got += len(buf)
                if progress:
                    progress(done)
        if expect and got < expect:
            raise ConnectionError("connection dropped mid-file")


def need_space(root: str, need: float):
    free = shutil.disk_usage(root).free
    if need + (200 << 20) > free:
        raise DownloadError(f"Not enough disk space: the download needs {need / 1e9:.1f} GB "
                            f"and this Mac has {free / 1e9:.1f} GB free.")


def download_all(root: str, files=FILES, progress=None, **kw):
    """Fetch every missing entry. progress(done_bytes, total_bytes). Raises DownloadError."""
    todo = missing(root, files)
    if not todo:
        return
    total = sum(e[3] for e in todo)
    os.makedirs(root, exist_ok=True)
    need_space(root, total - sum(_have(os.path.join(root, e[0]) + ".part") for e in todo))
    base = 0
    for rel, url, sha, size in todo:
        fetch(url, os.path.join(root, rel), sha, size,
              (lambda n, b=base: progress(b + n, total)) if progress else None, **kw)
        base += size
    if progress:
        progress(total, total)


def _cli(argv):
    samples = "--samples" in argv
    args = [a for a in argv if a != "--samples"]
    root = args[0] if args else ("samples" if samples else "models")
    files = SAMPLES if samples else FILES
    last = [0.0]

    def show(done, total):
        if time.time() - last[0] > 0.5 or done == total:
            last[0] = time.time()
            pct = f"{100 * done / total:5.1f}%" if total else ""
            print(f"\r  {done / 1e6:8.1f} MB {pct}", end="", flush=True)

    for e in files:
        print(("✓ " if e not in missing(root, [e]) else "↓ ") + os.path.join(root, e[0]))
    try:
        download_all(root, files, show)
    except DownloadError as e:
        print(f"\n✗ {e}", file=sys.stderr)
        return 1
    print("\ndone")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
