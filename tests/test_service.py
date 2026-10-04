import asyncio
import hashlib
import io
import json
import os
import signal
import sys
import time
import wave
import zipfile

import pytest
from fastapi.testclient import TestClient

from hushscript.app import Job, Manager, Settings, create_app
from hushscript.audio import AudioError, decode
from hushscript.exports import bundle, clean_name, render, segments_from_words
from hushscript.privacy import anonymous_file


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        models=str(tmp_path), max_bytes=1024, hosts=["testserver"], origins=["http://testserver"]
    )
    app = create_app(settings, probe=lambda: [], protect=False)
    with TestClient(app) as client:
        yield client


def reserve(client, name="interview.wav"):
    response = client.post("/api/jobs", json={"filename": name})
    assert response.status_code == 201
    job = response.json()
    return "/api/jobs/" + job["id"], {"Authorization": "Bearer " + job["token"]}


def test_job_capability_and_single_upload_slot(client):
    path, headers = reserve(client)
    assert client.get(path).status_code == 404
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 404
    assert client.post("/api/jobs", json={"filename": "other.wav"}).status_code == 409
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get(path, headers=headers).status_code == 404
    assert client.post("/api/jobs", json={"filename": "other.wav"}).status_code == 201


@pytest.mark.parametrize(("body", "expected"), [(b"", 400), (b"x" * 1025, 413)])
def test_upload_limits_dispose_job_and_release_slot(client, body, expected):
    path, headers = reserve(client)
    assert client.put(path + "/audio", headers=headers, content=body).status_code == expected
    assert client.get(path, headers=headers).status_code == 404
    assert not client.app.state.manager.jobs


def test_streamed_upload_limit_without_content_length(client):
    path, headers = reserve(client)
    response = client.put(path + "/audio", headers=headers, content=iter([b"x" * 600, b"x" * 600]))
    assert response.status_code == 413
    assert not client.app.state.manager.jobs


def test_foreign_origin_and_host_rejected(client):
    assert (
        client.post(
            "/api/jobs", headers={"Origin": "https://evil.invalid"}, json={"filename": "x"}
        ).status_code
        == 403
    )
    assert client.get("/api/health", headers={"Host": "evil.invalid"}).status_code == 400


def test_offline_ui_headers_and_local_assets(client):
    for path in ("/", "/app.js", "/style.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "http" not in client.get("/").text
    assert client.get("/docs").status_code == 404


def test_fail_closed_when_protections_absent():
    app = create_app(
        Settings(hosts=["testserver"]), probe=lambda: ["Guard unavailable"], protect=False
    )
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ready"] is False
        assert c.post("/api/jobs", json={"filename": "x"}).status_code == 503


def test_result_export_acknowledgement_and_cross_job_isolation(client):
    path, headers = reserve(client)
    job = next(iter(client.app.state.manager.jobs.values()))
    job.phase = "ready"
    job.result = sample_result()
    response = client.get(path + "/result?format=zip", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["transcript.json", "transcript.md", "transcript.txt"]
        assert json.loads(archive.read("transcript.json"))["schema_version"] == "1.0"
    second, second_headers = reserve(client)
    assert client.get(path + "/result", headers=second_headers).status_code == 404
    assert client.delete(path, headers=headers).status_code == 204
    assert job.result is None and job.filename == ""
    assert client.get(path + "/result", headers=headers).status_code == 404
    assert client.get(second, headers=second_headers).status_code == 200


def test_abandoned_jobs_and_expired_results_reaped():
    async def check():
        manager = Manager(Settings(retention=0, disconnect_timeout=0), lambda: [])
        for phase in ("reserved", "processing", "ready"):
            job = Job(
                phase,
                hashlib.sha256(b"x").digest(),
                "test.wav",
                False,
                phase=phase,
                created=time.monotonic() - 100,
                touched=time.monotonic() - 100,
            )
            job.fd = anonymous_file("test")
            if phase == "ready":
                job.result = sample_result()
                job.finished = time.monotonic() - 10
            manager.jobs[job.id] = job
        jobs = list(manager.jobs.values())
        reaper = asyncio.create_task(manager.reap())
        await asyncio.sleep(1.15)
        reaper.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reaper
        assert not manager.jobs
        assert all(j.fd is None and j.result is None for j in jobs)

    asyncio.run(check())


def test_cancel_kills_actual_child_and_closes_audio_fd():
    async def check():
        manager = Manager(Settings(), lambda: [])
        job = Job("x", b"", "x", False, phase="processing")
        job.fd = anonymous_file("test")
        old_fd = job.fd
        job.process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(30)", start_new_session=True
        )
        manager.jobs[job.id] = job
        await manager.dispose(job)
        assert job.process.returncode == -signal.SIGKILL
        assert not manager.jobs
        with pytest.raises(OSError):
            os.fstat(old_fd)
        await manager.dispose(job)

    asyncio.run(check())


def test_audio_decode_and_duration_limit():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 3200)
    fd = anonymous_file("test")
    try:
        os.write(fd, buffer.getvalue())
        samples = decode(fd)
        assert len(samples) == 3200
        assert not samples.any()
        with pytest.raises(AudioError, match="limit"):
            decode(fd, max_seconds=0.1)
    finally:
        os.close(fd)


def test_invalid_audio_rejected_without_content_in_error():
    fd = anonymous_file("test")
    try:
        os.write(fd, b"private malformed input")
        with pytest.raises(AudioError, match="damaged or its format is unsupported"):
            decode(fd)
    finally:
        os.close(fd)


def sample_result():
    words = [
        {"start": 0.0, "end": 1.0, "speaker": "speaker_1", "text": "Hello."},
        {"start": 1.2, "end": 2.0, "speaker": "speaker_2", "text": "Hi!"},
    ]
    return {
        "schema_version": "1.0",
        "source": {"filename": "<script>.wav"},
        "text": "Hello. Hi!",
        "segments": segments_from_words(words),
        "warnings": [],
    }


def test_exports_timestamps_speakers_and_literal_markdown():
    result = sample_result()
    exports = render(result)
    assert "[00:00:00] Speaker 1: Hello." in exports["transcript.txt"]
    assert len(result["segments"]) == 2
    assert "\\!" in exports["transcript.md"]
    assert "<script" not in exports["transcript.md"]
    assert clean_name("../../secret/meeting\n.wav") == "meeting.wav"
    assert bundle(result).startswith(b"PK")
