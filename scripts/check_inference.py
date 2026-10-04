"""Real API checks. Run in a no-swap container while the host guard is active."""

import argparse
import io
import json
import re
import time
import urllib.error
import urllib.request
import wave
import zipfile
from pathlib import Path

from hushscript.privacy import protect_process

BASE = "http://127.0.0.1:8787"
FIXTURES = "https://raw.githubusercontent.com/NVIDIA/NeMo-Speech.cpp/v0.2.0/test_files/"


def guard():
    if Path("/sys/fs/cgroup/memory.swap.max").read_text().strip() != "0":
        raise RuntimeError("Run this check inside a container with swap disabled.")
    state = json.loads(Path("/host-guard/status.json").read_text())
    if not state.get("protected") or not -2 <= time.time() - state["updated_at"] <= 8:
        raise RuntimeError("The host privacy guard must be active.")


def request(path, *, method="GET", token=None, data=None, binary=False):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    elif data is not None:
        headers["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(BASE + path, method=method, headers=headers, data=data)
    with urllib.request.urlopen(req, timeout=150) as response:
        body = response.read()
    return body if binary else json.loads(body) if body else None


def run_audio(audio, *, name, diarize=False, fail=False):
    guard()
    job = request("/api/jobs", method="POST", data={"filename": name, "diarize": diarize})
    path, token = "/api/jobs/" + job["id"], job["token"]
    try:
        request(path + "/audio", method="PUT", token=token, data=audio)
        until = time.monotonic() + 1800
        while time.monotonic() < until:
            guard()
            status = request(path, token=token)
            if status["status"] not in {"processing", "uploading"}:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Test inference exceeded the processing deadline")
        if fail:
            assert status["status"] == "failed", status["status"]
            return {"status": "failed"}
        if status["status"] != "ready":
            raise RuntimeError(status.get("error") or "Inference did not complete")
        result = request(path + "/result", token=token)
        with zipfile.ZipFile(
            io.BytesIO(request(path + "/result?format=zip", token=token, binary=True))
        ) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == 3
            assert json.loads(archive.read("transcript.json"))["text"] == result["text"]
        words = [word for segment in result["segments"] for word in segment["words"]]
        assert result["schema_version"] == "1.0"
        assert all(0 <= w["start"] <= w["end"] <= result["duration_seconds"] + 0.001 for w in words)
        assert all(a["start"] <= b["start"] for a, b in zip(words, words[1:], strict=False))
        return result
    finally:
        request(path, method="DELETE", token=token)
        try:
            request(path, token=token)
        except urllib.error.HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("Acknowledged result remained accessible")


def wav_bytes(frames, *, rate=16000, width=2, channels=1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return buffer.getvalue()


def metrics(name, result):
    print(
        json.dumps(
            {
                "fixture": name,
                "duration_seconds": result.get("duration_seconds"),
                "processing_seconds": result.get("processing_seconds"),
                "speaker_labels": len(result.get("speakers", [])),
                "word_count": sum(len(s["words"]) for s in result.get("segments", [])),
                "device": result.get("model", {}).get("device"),
            }
        ),
        flush=True,
    )


def main():
    global BASE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--long", action="store_true", help="Also run a repeated ten-minute sample")
    ap.add_argument("--base-url", default=BASE)
    args = ap.parse_args()
    BASE = args.base_url
    protect_process()
    guard()
    assert request("/api/health")["ready"]
    with urllib.request.urlopen(FIXTURES + "asr/wav/test/jfk.wav", timeout=60) as response:
        jfk = bytearray(response.read())
    try:
        result = run_audio(jfk, name="public-jfk.wav")
        normalized = re.sub(r"[^a-z ]", "", result["text"].lower())
        assert "ask not what your country can do for you" in normalized
        metrics("jfk", result)
        result = run_audio(wav_bytes(b"\0\0" * 16000), name="generated-silence.wav")
        assert result["text"] == "" and result["segments"] == []
        metrics("generated-silence", result)
        run_audio(b"invalid public test bytes", name="malformed.wav", fail=True)
        print(json.dumps({"fixture": "malformed", "rejected_and_deleted": True}), flush=True)
        with urllib.request.urlopen(FIXTURES + "diar/ami_en2002d_2132.wav", timeout=60) as response:
            ami = bytearray(response.read())
        try:
            result = run_audio(ami, name="public-ami.wav", diarize=True)
            assert result["diarization"] and result["speakers"]
            metrics("ami-four-speaker-reference", result)
            # Alternate clean excerpts from only two reference speakers. This is a
            # constructed fixture, not a representative interview quality benchmark.
            with wave.open(io.BytesIO(ami), "rb") as wav:
                rate, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels()
                frames = wav.readframes(wav.getnframes())
            spans = [
                (3.2, 14.5),
                (28.75, 31.1),
                (17.1, 19.5),
                (34.15, 36.8),
                (3.2, 14.5),
                (37.25, 39.5),
                (17.1, 19.5),
                (40.85, 43.0),
            ]
            parts = []
            for begin, end in spans:
                parts.append(
                    frames[
                        int(begin * rate) * width * channels : int(end * rate) * width * channels
                    ]
                )
                parts.append(b"\0" * int(rate * 0.4) * width * channels)
            result = run_audio(
                wav_bytes(b"".join(parts * 2), rate=rate, width=width, channels=channels),
                name="constructed-two-speaker.wav",
                diarize=True,
            )
            metrics("constructed-two-speaker", result)
            assert result["segments"][-1]["end"] > 75
            assert len(result["speakers"]) == 2, "Constructed fixture did not yield two speakers"
        finally:
            ami[:] = b"\0" * len(ami)
        if args.long:
            with wave.open(io.BytesIO(jfk), "rb") as wav:
                rate, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels()
                frames = wav.readframes(wav.getnframes())
            target = 600 * rate * width * channels
            frames = (frames * (target // len(frames) + 1))[:target]
            result = run_audio(
                wav_bytes(frames, rate=rate, width=width, channels=channels),
                name="repeated-ten-minute-public-fixture.wav",
            )
            metrics("repeated-jfk-ten-minutes", result)
            assert abs(result["duration_seconds"] - 600) < 0.01
            assert result["segments"][-1]["end"] > 590
        print("Actual inference/API checks completed; all test jobs acknowledged and removed.")
    finally:
        jfk[:] = b"\0" * len(jfk)


if __name__ == "__main__":
    main()
