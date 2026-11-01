import os

import numpy as np
import pytest

from lipflow.face import STABLE_REFERENCE, mouth_rois
from lipflow.vsr import MODEL_FPS, LipReader

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "samples", "2016-03-12.mov")


def test_resample_to_25fps():
    ts = [i / 30 for i in range(90)]  # 3 s at 30 fps
    idx = LipReader.resample(ts, len(ts))
    assert abs(len(idx) - 3 * MODEL_FPS) <= 1
    assert idx == sorted(idx) and idx[-1] <= 89


def test_mouth_rois_shape_and_interpolation():
    frames = [np.full((480, 640), 128, np.uint8) for _ in range(10)]
    anchors = [None] * 10
    anchors[2] = anchors[7] = STABLE_REFERENCE * 1.5 + 50  # face found in only 2 frames
    rois = mouth_rois(frames, anchors)
    assert rois.shape == (10, 96, 96) and rois.dtype == np.uint8
    assert mouth_rois(frames, [None] * 10) is None


def test_tensor_layout():
    x = LipReader.to_tensor(np.zeros((30, 96, 96), np.uint8))
    assert tuple(x.shape) == (1, 30, 88, 88)  # (C, T, H, W): the conv3d frontend wants B, C, T, H, W


@pytest.mark.skipif(not os.path.exists(SAMPLE), reason="run ./setup.sh --samples")
def test_reads_a_real_clip():
    from lipflow.offline import transcribe_file
    text = transcribe_file(SAMPLE, LipReader(beam_size=10), 20.4, 28.1)
    words = set(text.split())
    truth = set("BORN IN NEW YORK CITY AND RAISED MOSTLY IN CHICAGO NANCY DAVIS GRADUATED FROM SMITH COLLEGE".split())
    assert len(words & truth) / len(truth) > 0.8, text


def test_face_crop_offsets_give_the_same_mouth_patch():
    """A crop + offset must produce exactly the patch the full frame would."""
    rng = np.random.default_rng(0)
    frames = [rng.integers(0, 255, (720, 1280), dtype=np.uint8) for _ in range(5)]
    anchors = [STABLE_REFERENCE * 2.0 + (400, 200) for _ in range(5)]
    full = mouth_rois(frames, anchors)
    crops = [(f[150:650, 300:900], (300, 150)) for f in frames]
    assert np.abs(mouth_rois(crops, anchors).astype(int) - full.astype(int)).max() <= 1


def test_mic_segment_aligns_to_video_clock():
    from lipflow import mic
    rate = mic.RATE
    t = np.arange(rate * 2) / rate
    wave = np.sin(2 * np.pi * 5 * t).astype(np.float32)
    start = 1000.0
    chunks = [(start + i / rate, wave[i:i + 1600]) for i in range(0, len(wave), 1600)]
    seg = mic.segment(chunks, start + 0.5 + mic.CAMERA_LATENCY, 25)  # 1 s of video starting at +0.5 s
    assert len(seg) == 16000
    assert np.allclose(seg, wave[8000:24000], atol=1e-6)


def test_mic_lag_found_from_mouth_vs_loudness():
    """A Bluetooth mic's audio arrives late; calibrate() recovers the delay and segment() undoes it."""
    from lipflow import mic
    rng = np.random.default_rng(1)
    rate, n = mic.RATE, 100  # 4 s of video at 25 fps
    mouth = np.convolve(rng.random(n + 10), np.ones(5) / 5, "valid")[:n].astype(np.float32)  # smooth open/close
    whisper = (rng.standard_normal(n * 640) * np.repeat(mouth, 640)).astype(np.float32)  # loud when mouth open
    t0, true_lag = 1000.0, 0.2
    stamp = t0 - mic.CAMERA_LATENCY + true_lag  # audio stamped 0.2 s late
    padded = np.concatenate([np.zeros(rate, np.float32), whisper, np.zeros(rate, np.float32)])
    chunks = [(stamp - 1 + i / rate, padded[i:i + 1600]) for i in range(0, len(padded), 1600)]

    m = mic.Mic("AirPods Pro")
    assert m.keep_open and not mic.Mic().keep_open
    assert m.calibrate(chunks, t0, mouth) == true_lag
    assert np.allclose(mic.segment(chunks, t0, n, lag=m.lag), whisper, atol=1e-6)  # back in sync
    assert np.corrcoef(mic.segment(chunks, t0, n)[:640 * 90], whisper[:640 * 90])[0, 1] < 0.5  # lag=0 isn't
    assert mic.estimate_lag(chunks, t0, mouth[:20]) is None  # too short to trust
