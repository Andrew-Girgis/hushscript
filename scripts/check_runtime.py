"""Exercise actual API cancellation and interrupted uploads with public/synthetic data."""

import http.client
import io
import json
import time
import urllib.error
import urllib.request
import wave

from check_inference import FIXTURES, guard, request, run_audio, wav_bytes

from hushscript.privacy import protect_process


def absent(path, token):
    try:
        request(path, token=token)
    except urllib.error.HTTPError as error:
        return error.code == 404
    return False


def main():
    protect_process()
    guard()
    with urllib.request.urlopen(FIXTURES + "asr/wav/test/jfk.wav", timeout=60) as response:
        source = bytearray(response.read())
    try:
        with wave.open(io.BytesIO(source), "rb") as wav:
            rate, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels()
            frames = wav.readframes(wav.getnframes())
        target = 600 * rate * width * channels
        long_audio = wav_bytes(
            (frames * (target // len(frames) + 1))[:target],
            rate=rate,
            width=width,
            channels=channels,
        )
        job = request("/api/jobs", method="POST", data={"filename": "cancel-public.wav"})
        path, token = "/api/jobs/" + job["id"], job["token"]
        try:
            request(path + "/audio", method="PUT", token=token, data=long_audio)
            time.sleep(0.2)
            status = request(path, token=token)
            assert status["status"] == "processing", "Cancellation did not catch active inference"
            start = time.monotonic()
            request(path, method="DELETE", token=token)
            assert absent(path, token)
            print(
                json.dumps(
                    {
                        "cancelled_active_inference": True,
                        "cancel_seconds": round(time.monotonic() - start, 3),
                    }
                ),
                flush=True,
            )
        finally:
            if not absent(path, token):
                request(path, method="DELETE", token=token)

        job = request("/api/jobs", method="POST", data={"filename": "interrupted.wav"})
        path, token = "/api/jobs/" + job["id"], job["token"]
        connection = http.client.HTTPConnection("127.0.0.1", 8787, timeout=10)
        connection.putrequest("PUT", path + "/audio")
        connection.putheader("Authorization", "Bearer " + token)
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("Content-Length", "1000000")
        connection.endheaders()
        connection.send(b"\0" * 1024)
        time.sleep(0.1)
        connection.close()
        until = time.monotonic() + 5
        while time.monotonic() < until and not absent(path, token):
            time.sleep(0.1)
        assert absent(path, token), "Interrupted upload was retained"
        print(json.dumps({"interrupted_upload_removed": True}), flush=True)
        result = run_audio(wav_bytes(b"\0\0" * 16000), name="after-cancel-silence.wav")
        assert not result["text"]
        print(json.dumps({"worker_slot_reusable": True}), flush=True)
    finally:
        source[:] = b"\0" * len(source)


if __name__ == "__main__":
    main()
