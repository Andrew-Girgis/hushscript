"""WSL2 launcher using a separate Windows host guard. No host settings are changed."""

import json
import os
import platform
import queue
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from provision_tls import provision, provision_pem

ROOT = Path(__file__).resolve().parents[1]
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]


def guest_problems(*, release=None, command_line=None, swaps=None):
    release = release if release is not None else platform.release()
    command_line = command_line if command_line is not None else Path("/proc/cmdline").read_text()
    swaps = swaps if swaps is not None else Path("/proc/swaps").read_text()
    problems = []
    if "microsoft" not in release.lower() or "wsl2" not in release.lower():
        problems.append("A WSL2 Linux distribution is required.")
    if "WSL_ENABLE_CRASH_DUMP=1" in command_line.split():
        problems.append("The running WSL VM still enables dump collection. Restart WSL.")
    lines = swaps.strip().splitlines()
    if not lines or not lines[0].startswith("Filename"):
        problems.append("Cannot verify the WSL swap table.")
    elif len(lines) > 1:
        problems.append("WSL swap is active. Set [wsl2] swap=0 and restart WSL.")
    return problems


def state_problems(state, now=None):
    now = time.time() if now is None else now
    if not isinstance(state, dict):
        return ["Invalid Windows guard response."]
    stamp = state.get("updated_at")
    if type(stamp) not in (int, float) or not -2 <= now - stamp <= 6:
        return ["Windows host protection report is stale."]
    if state.get("protected") is not True:
        return state.get("problems") or ["Windows host protection is not ready."]
    if state.get("problems"):
        return ["Windows guard reported conflicting protection state."]
    return []


def launch(args, pem=None):
    if args.gpu:
        raise SystemExit(
            "The WSL2 launcher currently supports CPU mode; NVIDIA remains unverified."
        )
    if not (args.local_tls or args.tls_domain):
        raise SystemExit("WSL2 requires TLS across its host forwarder. See docs/WSL.md.")
    problems = guest_problems()
    if problems:
        raise SystemExit(" ".join(problems))
    info = json.loads(subprocess.check_output([*DOCKER, "info", "--format", "{{json .}}"]))
    if (
        info.get("CgroupVersion") != "2"
        or info.get("KernelVersion") != platform.release()
        or "desktop" in info.get("OperatingSystem", "").lower()
    ):
        raise SystemExit("Use Docker Engine inside this WSL2 distro with cgroup v2.")
    distro = os.environ.get("WSL_DISTRO_NAME")
    powershell = shutil.which("powershell.exe")
    if not distro or not powershell:
        raise SystemExit("Windows PowerShell interop and WSL_DISTRO_NAME are required.")
    script = subprocess.check_output(
        ["wslpath", "-w", str(ROOT / "scripts/windows_guard.ps1")], text=True
    ).strip()
    command = [
        *DOCKER,
        "compose",
        "-f",
        str(ROOT / "compose.yaml"),
        "-f",
        str(ROOT / "compose.tls.yaml"),
    ]
    if args.tls_domain:
        os.environ["HUSHSCRIPT_HOSTS"] = args.tls_domain
        os.environ["HUSHSCRIPT_ORIGINS"] = f"https://{args.tls_domain}:8445"
    else:
        os.environ["HUSHSCRIPT_ORIGINS"] = "https://localhost:8787,https://127.0.0.1:8787"
    guard = ROOT / ".runtime/host-guard"
    guard.mkdir(parents=True, exist_ok=True)
    guard.chmod(0o755)
    stop = threading.Event()
    messages = queue.Queue()
    failed = []

    def write_state(protected):
        pending = guard / "status.new"
        pending.write_text(json.dumps({"protected": protected, "updated_at": time.time()}))
        pending.chmod(0o644)
        pending.replace(guard / "status.json")

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    import pwd

    linux_user = pwd.getpwuid(os.getuid()).pw_name
    helper = subprocess.Popen(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script,
            "-Watch",
            "-Distribution",
            distro,
            "-ProjectRoot",
            str(ROOT),
            "-LinuxUser",
            linux_user,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    def read_messages():
        try:
            for line in helper.stdout:
                messages.put(json.loads(line.lstrip("\ufeff")))
        except (ValueError, OSError):
            pass
        finally:
            messages.put(None)

    threading.Thread(target=read_messages, daemon=True).start()

    def next_state(timeout):
        state = messages.get(timeout=timeout)
        issues = state_problems(state) + guest_problems()
        if issues:
            raise RuntimeError(" ".join(issues))

    def heartbeat():
        while not stop.is_set():
            try:
                next_state(6)
                write_state(True)
            except Exception as error:
                failed.append(str(error) or "Windows guard heartbeat stopped.")
                write_state(False)
                stop.set()

    try:
        write_state(False)
        next_state(30)
        write_state(True)
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        subprocess.run([*command, "up", "-d", "--no-build"], check=True, cwd=ROOT)
        if args.tls_domain:
            provision(command, args.tls_domain)
        else:
            provision_pem(command, pem)
        address = f"https://{args.tls_domain}:8445" if args.tls_domain else "https://localhost:8787"
        print(f"Hushscript: {address} — Ctrl+C stops and clears server memory.", flush=True)
        stop.wait()
        if failed:
            raise RuntimeError(failed[0])
    finally:
        stop.set()
        if "thread" in locals():
            thread.join(timeout=7)
        write_state(False)
        try:
            # Also stop locally if the Windows helper has already exited or crashed.
            subprocess.run([*command, "stop", "-t", "3"], check=True, cwd=ROOT, timeout=30)
        finally:
            helper.stdin.close()
            # Keep the independent Windows power request until Docker stops.
            helper.wait()
