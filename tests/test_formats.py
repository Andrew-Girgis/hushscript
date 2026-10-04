"""Verify the advertised container formats with real in-memory codec output."""

import io
import os

import av
import numpy as np
import pytest

from hushscript.audio import decode
from hushscript.privacy import anonymous_file


@pytest.mark.parametrize(
    "container_format,codec",
    [
        ("wav", "pcm_s16le"),
        ("mp3", "libmp3lame"),
        ("mp4", "aac"),
        ("flac", "flac"),
        ("ogg", "libopus"),
        ("adts", "aac"),
        ("webm", "libopus"),
    ],
)
def test_advertised_formats_decode_without_disk(container_format, codec):
    rate = 48000
    tone = (0.1 * np.sin(2 * np.pi * 220 * np.arange(rate * 2) / rate)).astype(np.float32)
    encoded = io.BytesIO()
    with av.open(encoded, mode="w", format=container_format) as output:
        stream = output.add_stream(codec, rate=rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(tone.reshape(1, -1), format="fltp", layout="mono")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    fd = anonymous_file()
    try:
        os.write(fd, encoded.getvalue())
        samples = decode(fd)
        assert 1.9 < len(samples) / 16000 < 2.2
        assert np.max(np.abs(samples)) > 0.05
    finally:
        os.close(fd)
