"""Bounded decoding from an anonymous in-memory file descriptor."""

import os

import av
import numpy as np

RATE = 16000


class AudioError(Exception):
    pass


def decode(fd, max_seconds=1200):
    av.logging.set_level(av.logging.PANIC)
    blocks = []
    count = 0
    limit = int(max_seconds * RATE)
    try:
        with os.fdopen(os.dup(fd), "rb") as source:
            source.seek(0)
            with av.open(
                source,
                options={
                    "protocol_whitelist": "pipe",
                    "format_whitelist": "wav,mp3,mov,flac,ogg,matroska,webm,aac",
                    "probesize": "1048576",
                    "analyzeduration": "5000000",
                    "max_streams": "8",
                },
            ) as container:
                if not container.streams.audio:
                    raise AudioError("No audio track was found.")
                stream = container.streams.audio[0]
                if len(stream.codec_context.layout.channels) > 8:
                    raise AudioError("Audio with more than eight channels is unsupported.")
                resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
                for frame in container.decode(stream):
                    for converted in resampler.resample(frame):
                        block = converted.to_ndarray().reshape(-1)
                        count += len(block)
                        if count > limit:
                            raise AudioError(f"Audio exceeds the {max_seconds // 60}-minute limit.")
                        blocks.append(block)
                for converted in resampler.resample(None):
                    block = converted.to_ndarray().reshape(-1)
                    count += len(block)
                    if count > limit:
                        raise AudioError(f"Audio exceeds the {max_seconds // 60}-minute limit.")
                    blocks.append(block)
        if not count:
            raise AudioError("The file contains no decodable audio.")
        samples = np.ascontiguousarray(np.concatenate(blocks), dtype=np.float32)
        if not np.isfinite(samples).all():
            raise AudioError("The audio contains invalid sample values.")
        return samples
    except AudioError:
        raise
    except Exception:
        raise AudioError("The audio is damaged or its format is unsupported.") from None
    finally:
        for block in blocks:
            block.fill(0)
