"""Exercise the real launcher loop with simulated Windows and Docker boundaries."""

import json
import pwd
import queue
import signal
import subprocess
import time
from types import SimpleNamespace

import pytest
import serve_wsl


@pytest.mark.parametrize(
    "scenario,expected_error",
    [
        ("rejected", "Host paging enabled"),
        ("startup_failure", "returned non-zero exit status"),
        ("certificate_failure", "Certificate unavailable"),
        ("guard_exit", "Invalid Windows guard response"),
        ("guard_loss", "Host paging enabled"),
        ("signal", None),
    ],
)
def test_launcher_stops_docker_and_revokes_guard_on_each_exit(
    monkeypatch, tmp_path, scenario, expected_error
):
    # No Windows machine, Docker daemon, audio, or real host guard is touched.
    events = []
    handlers = {}
    replies = queue.Queue()
    guard = tmp_path / ".runtime/host-guard/status.json"
    release = "6.6-microsoft-standard-WSL2"

    def state(protected=True):
        return {
            "protected": protected,
            "updated_at": time.time(),
            "problems": [] if protected else ["Host paging enabled"],
        }

    def output():
        if scenario == "rejected":
            yield json.dumps(state(False)) + "\n"
            return
        while True:
            try:
                reply = replies.get(timeout=0.01)
            except queue.Empty:
                reply = state()
            if reply is None:
                return
            yield json.dumps(reply) + "\n"

    class Helper:
        def __init__(self):
            self.stdout = output()
            self.stdin = SimpleNamespace(close=lambda: replies.put(None))

        def wait(self):
            assert events[-1] == "docker_stopped"
            assert not json.loads(guard.read_text())["protected"]
            events.append("helper_released")
            return 0

    helper = Helper()

    def check_output(command, **kwargs):
        if command[0] == "wslpath":
            return "C:\\synthetic\\windows_guard.ps1"
        assert command[: len(serve_wsl.DOCKER)] == serve_wsl.DOCKER
        return json.dumps(
            {"CgroupVersion": "2", "KernelVersion": release, "OperatingSystem": "Ubuntu"}
        ).encode()

    def run(command, **kwargs):
        if "up" in command:
            assert json.loads(guard.read_text())["protected"]
            events.append("docker_started")
            if scenario == "startup_failure":
                raise subprocess.CalledProcessError(1, command)
        else:
            assert "stop" in command
            assert not json.loads(guard.read_text())["protected"]
            events.append("docker_stopped")
        return SimpleNamespace(returncode=0)

    def provision(*args):
        assert events[-1] == "docker_started"
        events.append("tls_loaded")
        if scenario == "certificate_failure":
            raise RuntimeError("Certificate unavailable")
        if scenario == "guard_exit":
            replies.put(None)
        elif scenario == "guard_loss":
            replies.put(state(False))
        else:
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="synthetic"))
    monkeypatch.setattr(serve_wsl, "ROOT", tmp_path)
    monkeypatch.setattr(serve_wsl, "guest_problems", lambda: [])
    monkeypatch.setattr(serve_wsl.platform, "release", lambda: release)
    monkeypatch.setattr(serve_wsl.shutil, "which", lambda name: name)
    monkeypatch.setattr(
        serve_wsl.signal, "signal", lambda sig, handler: handlers.update({sig: handler})
    )
    monkeypatch.setattr(serve_wsl.subprocess, "check_output", check_output)
    monkeypatch.setattr(serve_wsl.subprocess, "Popen", lambda *a, **kw: helper)
    monkeypatch.setattr(serve_wsl.subprocess, "run", run)
    monkeypatch.setattr(serve_wsl, "provision_pem", provision)
    monkeypatch.setenv("WSL_DISTRO_NAME", "SyntheticUbuntu")
    # Restore the launcher's process environment changes when the test ends.
    monkeypatch.setenv("HUSHSCRIPT_ORIGINS", "")
    args = SimpleNamespace(gpu=False, local_tls=True, tls_domain=None)
    if expected_error:
        with pytest.raises((RuntimeError, subprocess.CalledProcessError), match=expected_error):
            serve_wsl.launch(args, "synthetic TLS material")
    else:
        serve_wsl.launch(args, "synthetic TLS material")
    assert events[-2:] == ["docker_stopped", "helper_released"]
    if scenario == "rejected":
        assert "docker_started" not in events
        assert "tls_loaded" not in events
