"""Microphone for whisper mode: on only while you hold the key, timestamped on the same clock as
the camera frames, so the audio can be cut to exactly the recorded video.

Timing matters: on test clips, audio 0.4 s off the video doubled the word error rate.
"""
from __future__ import annotations

import threading
import time

import numpy as np

RATE = 16000
CAMERA_LATENCY = 0.06  # a frame is read ~2 frames after it was exposed


class Mic:
    """device: a name from input_devices(), or None / "auto" for the Mac's built-in mic.

    Any other mic (AirPods) is kept open while whisper mode is on: opening a Bluetooth mic flips the
    headset into call mode, which takes about a second and would cut off your first words.
    `lag` is how late this mic's audio arrives (seconds), learned by `calibrate`.
    """

    def __init__(self, device=None, lag: float = 0.0):
        self.name = None if device in (None, "auto") else device
        self.lag = lag
        self.lags: list[float] = []  # recent per-clip estimates, newest last
        self._stream = None
        self._recording = False
        self._chunks: list[tuple[float, np.ndarray]] = []
        self._lock = threading.Lock()
        self.error: str | None = None

    @property
    def keep_open(self) -> bool:
        return self.name is not None

    @staticmethod
    def _builtin():
        """The Mac's own microphone, not a Continuity iPhone (same trap as the camera)."""
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and "iphone" not in d["name"].lower():
                    if "macbook" in d["name"].lower() or "built-in" in d["name"].lower():
                        return i
        except Exception:
            pass
        return None  # system default

    def _index(self):
        if self.name is None:
            return self._builtin()
        import sounddevice as sd  # indices shift when AirPods connect, so look the name up each time
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and d["name"] == self.name:
                return i
        raise RuntimeError(f"{self.name} isn't connected")

    def open(self):
        """Start the input stream (no-op if it's already running)."""
        if self._stream is not None and self._stream.active:
            return
        self.close()
        import sounddevice as sd
        try:
            self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", device=self._index(),
                                          blocksize=0, callback=self._cb)
            self._stream.start()
            self.error = None
        except Exception as e:
            self.error = str(e)
            self._stream = None
            print(f"[mouthpiece] microphone unavailable: {e}")

    def start(self):
        with self._lock:
            self._chunks = []
            self._recording = True
        self.open()

    def _cb(self, data, frames, t, status):
        if not self._recording:
            return
        # time of the first sample in this block, on time.time()'s clock
        latency = self._stream.latency if self._stream is not None else 0.0
        t0 = time.time() - frames / RATE - float(latency or 0.0)
        with self._lock:
            self._chunks.append((t0, data[:, 0].copy()))

    def stop(self) -> list[tuple[float, np.ndarray]]:
        """Stop recording; the stream stays open for a kept-open mic."""
        self._recording = False
        if not self.keep_open:
            self.close()
        with self._lock:
            chunks, self._chunks = self._chunks, []
        return chunks

    def close(self):
        self._recording = False
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def calibrate(self, chunks, t_start: float, mouth_open, keep: int = 9) -> float:
        """Learn this mic's lag from one clip, set self.lag to the median of recent clips, return it."""
        est = estimate_lag(chunks, t_start, mouth_open)
        if est is not None:
            self.lags = (self.lags + [est])[-keep:]
            self.lag = float(np.median(self.lags))
        return self.lag


def input_devices() -> list[str]:
    try:
        import sounddevice as sd
        return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
    except Exception:
        return []


def estimate_lag(chunks, t_start: float, mouth_open, lo: float = -0.1, hi: float = 0.6,
                 min_frames: int = 50, min_corr: float = 0.3) -> "float | None":
    """How late the audio is vs the video, found by lining up mouth opening with loudness.

    Whispered sound follows the mouth, so the shift where the two correlate best is the lag. On a
    clip delayed by a known 0.1/0.2/0.3 s it finds it to within one frame. None if the clip is too
    short (2 s) or the match too weak to trust.
    ponytail: whole-frame (40 ms) envelope; finer resolution isn't needed, the model tolerates ~0.1 s.
    """
    m = np.asarray(mouth_open, np.float32)
    if len(m) < min_frames or m.std() < 1e-3:
        return None
    best, best_c = None, min_corr
    for lag in np.arange(lo, hi + 1e-9, 0.02):
        w = segment(chunks, t_start, len(m), lag=float(lag))
        if w is None:
            continue
        env = np.sqrt((w.reshape(len(m), -1) ** 2).mean(1))
        if env.std() < 1e-6:
            continue
        c = float(np.corrcoef(m, env)[0, 1])
        if c > best_c:
            best, best_c = round(float(lag), 2), c
    return best


def segment(chunks: list[tuple[float, np.ndarray]], t_start: float, n_frames: int, fps: int = 25,
            lag: float = 0.0) -> "np.ndarray | None":
    """Audio for n_frames video frames starting at t_start (video clock), 640 samples per frame.

    lag: how late this mic's audio arrives (Bluetooth adds ~0.1-0.3 s), so take audio stamped that much later."""
    if not chunks:
        return None
    t_start += lag - CAMERA_LATENCY
    want = n_frames * RATE // fps
    out = np.zeros(want, np.float32)
    got = 0
    for t0, a in chunks:
        off = int(round((t0 - t_start) * RATE))  # where this chunk lands in the output
        lo, hi = max(off, 0), min(off + len(a), want)
        if hi > lo:
            out[lo:hi] = a[lo - off:hi - off]
            got += hi - lo
    return out if got > want * 0.5 else None
