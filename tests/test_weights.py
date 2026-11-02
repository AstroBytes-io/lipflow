"""The model downloader against a local HTTP server: resume, checksum mismatch, retry. No network."""
import hashlib
import http.server
import os
import threading

import pytest

from mouthpiece import weights

DATA = os.urandom(300_000)
SHA = hashlib.sha256(DATA).hexdigest()


class Handler(http.server.BaseHTTPRequestHandler):
    fail_next = 0       # answer this many requests with 503
    ranges: list = []   # Range headers seen

    def do_GET(self):
        if Handler.fail_next:
            Handler.fail_next -= 1
            self.send_error(503)
            return
        rng = self.headers.get("Range")
        Handler.ranges.append(rng)
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        body = DATA[start:]
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def url():
    Handler.fail_next, Handler.ranges = 0, []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/model.pth"
    srv.shutdown()


def test_resumes_from_part_file(url, tmp_path):
    dest = tmp_path / "m" / "model.pth"
    dest.parent.mkdir()
    (tmp_path / "m" / "model.pth.part").write_bytes(DATA[:100_000])
    seen = []
    weights.fetch(url, str(dest), SHA, len(DATA), progress=seen.append)
    assert dest.read_bytes() == DATA
    assert Handler.ranges == ["bytes=100000-"]
    assert seen[0] == 100_000 and seen[-1] == len(DATA)
    assert not (tmp_path / "m" / "model.pth.part").exists()


def test_hash_mismatch_is_rejected_and_part_dropped(url, tmp_path):
    dest = tmp_path / "model.pth"
    with pytest.raises(weights.DownloadError, match="damaged"):
        weights.fetch(url, str(dest), "0" * 64, len(DATA))
    assert not dest.exists() and not (tmp_path / "model.pth.part").exists()


def test_retries_server_errors_then_succeeds(url, tmp_path):
    Handler.fail_next = 2
    dest = tmp_path / "model.pth"
    weights.fetch(url, str(dest), SHA, len(DATA), backoff=0.01)
    assert dest.read_bytes() == DATA


def test_gives_up_with_a_friendly_message_when_offline(tmp_path):
    with pytest.raises(weights.DownloadError, match="internet"):
        weights.fetch("http://127.0.0.1:9/x", str(tmp_path / "x"), retries=1, backoff=0.01)


def test_download_all_skips_present_files_and_reports_progress(url, tmp_path):
    files = [("a/model.pth", url, SHA, len(DATA)), ("b.pth", url, SHA, len(DATA))]
    (tmp_path / "b.pth").write_bytes(DATA)
    seen = []
    weights.download_all(str(tmp_path), files, lambda d, t: seen.append((d, t)), backoff=0.01)
    assert (tmp_path / "a" / "model.pth").read_bytes() == DATA
    assert len(Handler.ranges) == 1  # b.pth already there
    assert seen[-1] == (len(DATA), len(DATA))
    assert weights.missing(str(tmp_path), files) == []
    assert weights.corrupt(str(tmp_path), files) == []

