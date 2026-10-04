"""Public-fixture comparison; audio never leaves the guarded local process."""

import argparse
import ctypes
import json
import os
import re
import resource
import threading
import time
import urllib.request
from pathlib import Path

from hushscript.audio import decode
from hushscript.native import transcribe
from hushscript.privacy import anonymous_file, deny_network, protect_process

REFERENCE = (
    "And so my fellow Americans ask not what your country can do for you "
    "ask what you can do for your country"
)
FIXTURE = (
    "https://raw.githubusercontent.com/NVIDIA/NeMo-Speech.cpp/"
    "v0.2.0/test_files/asr/wav/test/jfk.wav"
)


def distance(reference, hypothesis):
    before = list(range(len(hypothesis) + 1))
    for i, a in enumerate(reference, 1):
        current = [i]
        for j, b in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, before[j] + 1, before[j - 1] + (a != b)))
        before = current
    return before[-1]


class GpuMemory:
    def __init__(self):
        self.stop = threading.Event()
        self.sampled = threading.Event()
        self.baseline = None
        self.peak = None
        self.thread = None
        self.lib = None

    def start(self):
        try:
            self.lib = ctypes.CDLL("libnvidia-ml.so.1")
            handle = ctypes.c_void_p()
            self.lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [
                ctypes.c_uint,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            if self.lib.nvmlInit_v2() or self.lib.nvmlDeviceGetHandleByIndex_v2(
                0, ctypes.byref(handle)
            ):
                return

            class Memory(ctypes.Structure):
                _fields_ = [
                    ("total", ctypes.c_uint64),
                    ("free", ctypes.c_uint64),
                    ("used", ctypes.c_uint64),
                ]

            self.lib.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory)]

            def sample():
                while not self.stop.is_set():
                    value = Memory()
                    if self.lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(value)) == 0:
                        if self.baseline is None:
                            self.baseline = value.used
                        self.peak = max(self.peak or 0, value.used)
                        self.sampled.set()
                    self.stop.wait(0.02)

            self.thread = threading.Thread(target=sample, daemon=True)
            self.thread.start()
            self.sampled.wait(timeout=1)
        except (OSError, AttributeError):
            self.lib = None

    def finish(self):
        self.stop.set()
        if self.thread:
            self.thread.join()
        if self.lib:
            self.lib.nvmlShutdown()
            self.lib = None
        if self.peak is None:
            return None
        return round(max(0, self.peak - self.baseline) / 1048576, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", choices=["parakeet", "whisper"], required=True)
    ap.add_argument("--device", choices=["cpu", "cuda"], required=True)
    args = ap.parse_args()
    protect_process()
    guard = json.loads(Path("/host-guard/status.json").read_text())
    assert guard["protected"] and 0 <= time.time() - guard["updated_at"] < 8
    assert Path("/sys/fs/cgroup/memory.swap.max").read_text().strip() == "0"
    with urllib.request.urlopen(FIXTURE, timeout=60) as response:
        audio = bytearray(response.read())
    fd = anonymous_file()
    samples = None
    gpu = GpuMemory()
    try:
        os.write(fd, audio)
        os.lseek(fd, 0, os.SEEK_SET)
        samples = decode(fd)
        os.close(fd)
        fd = None
        audio[:] = b"\0" * len(audio)
        deny_network()
        if args.device == "cuda":
            gpu.start()
        start = time.monotonic()
        if args.engine == "parakeet":
            text, _ = transcribe(
                samples,
                runtime_dir="/opt/nemo/current",
                model_dir="/models",
                device=args.device,
                diarize=False,
            )
        else:
            from faster_whisper import WhisperModel

            model = WhisperModel(
                "/models/whisper-turbo",
                device=args.device,
                compute_type="int8_float16" if args.device == "cuda" else "int8",
                cpu_threads=6,
                num_workers=1,
                local_files_only=True,
            )
            segments, _ = model.transcribe(
                samples, language="en", beam_size=5, vad_filter=False, word_timestamps=True
            )
            text = " ".join(segment.text for segment in segments)
        elapsed = time.monotonic() - start

        def normalize(value):
            return re.sub(r"[^a-z ]", "", value.lower()).split()

        reference, hypothesis = normalize(REFERENCE), normalize(text)
        print(
            json.dumps(
                {
                    "engine": args.engine,
                    "device": args.device,
                    "fixture": "jfk",
                    "duration_seconds": len(samples) / 16000,
                    "load_and_inference_seconds": round(elapsed, 3),
                    "word_error_rate": round(distance(reference, hypothesis) / len(reference), 4),
                    "peak_process_ram_mib": round(
                        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1
                    ),
                    "additional_gpu_memory_mib_approx": gpu.finish(),
                }
            ),
            flush=True,
        )
    finally:
        gpu.finish()
        if fd is not None:
            os.close(fd)
        if samples is not None:
            samples.fill(0)
        audio[:] = b"\0" * len(audio)


if __name__ == "__main__":
    main()
