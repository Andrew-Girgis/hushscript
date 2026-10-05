"""Start Hushscript with a verified host sleep inhibitor. No audio touches this process."""

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / ".runtime/host-guard"
WHO = "Hushscript-" + str(os.getpid())


def inhibitors():
    return json.loads(
        subprocess.check_output(["systemd-inhibit", "--list", "--json=short"], text=True, timeout=5)
    )


def configure_tls(args, command):
    if args.isolated_share:
        from share_node import app_running, domain

        command += ["-f", str(ROOT / "compose.isolated.yaml")]
        if app_running():
            raise SystemExit("Stop the current Hushscript launcher before isolated sharing.")
        name = domain(command)
        os.environ["HUSHSCRIPT_HOSTS"] = name
        os.environ["HUSHSCRIPT_ORIGINS"] = f"https://{name}:8445"
        return name
    if args.tls_domain:
        os.environ["HUSHSCRIPT_HOSTS"] = args.tls_domain
        os.environ["HUSHSCRIPT_ORIGINS"] = f"https://{args.tls_domain}:8445"
    else:
        os.environ["HUSHSCRIPT_ORIGINS"] = "https://localhost:8787,https://127.0.0.1:8787"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gpu", action="store_true", help="Use the NVIDIA CUDA image")
    ap.add_argument(
        "--elevate-inhibitor",
        action="store_true",
        help="Authorize the sleep inhibitor using sudo in a terminal or pkexec on the desktop",
    )
    tls = ap.add_mutually_exclusive_group()
    tls.add_argument("--tls-domain", help="Tailscale DNS name; HTTPS inside the container")
    tls.add_argument("--local-tls", action="store_true", help="Use HUSHSCRIPT_TLS_PEM from s")
    tls.add_argument(
        "--isolated-share",
        action="store_true",
        help="Serve through Hushscript's own isolated Tailscale node (native Linux)",
    )
    args = ap.parse_args()
    pem = os.environ.pop("HUSHSCRIPT_TLS_PEM", None)
    if args.local_tls and not pem:
        raise SystemExit("Inject HUSHSCRIPT_TLS_PEM using s. See docs/WSL.md.")
    if args.tls_domain and (
        not args.tls_domain.endswith(".ts.net")
        or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-." for c in args.tls_domain)
    ):
        raise SystemExit("Use the full lowercase Tailscale DNS name.")
    if args.isolated_share and (
        platform.system() != "Linux" or "microsoft" in platform.release().lower()
    ):
        raise SystemExit("Isolated sharing currently requires a native Linux host.")
    if platform.system() == "Linux" and "microsoft" in platform.release().lower():
        from serve_wsl import launch

        return launch(args, pem)
    if platform.system() != "Linux":
        raise SystemExit(
            "This launcher verifies native Linux host protections. See docs/PORTABILITY.md "
            "for Docker Desktop prerequisites; uploads remain disabled without a host guard."
        )
    info = json.loads(
        subprocess.check_output(["docker", "info", "--format", "{{json .}}"], text=True)
    )
    if (
        info.get("CgroupVersion") != "2"
        or "desktop" in info.get("OperatingSystem", "").lower()
        or info.get("KernelVersion") != platform.release()
    ):
        raise SystemExit("A local native Linux Docker engine with cgroup v2 is required.")
    cmd = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
    if args.gpu:
        cmd += ["-f", str(ROOT / "compose.gpu.yaml")]
    name = None
    if args.tls_domain or args.local_tls or args.isolated_share:
        cmd += ["-f", str(ROOT / "compose.tls.yaml")]
        name = configure_tls(args, cmd)
        if args.isolated_share:
            from share_node import domain

    GUARD.mkdir(parents=True, exist_ok=True)
    GUARD.chmod(0o755)
    stop = threading.Event()
    guard_failure = threading.Event()

    def shutdown(signum, frame):
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)

    def write_guard(protected):
        temp = GUARD / "status.new"
        temp.write_text(json.dumps({"protected": protected, "updated_at": time.time()}))
        temp.chmod(0o644)
        temp.replace(GUARD / "status.json")

    # The helper independently retains the inhibitor until the container has stopped,
    # even if this launcher is killed. Its stdin closes when the launcher exits.
    helper = ROOT / "scripts/inhibit_helper.py"
    inhibit_command = [
        "systemd-inhibit",
        "--what=sleep:shutdown",
        "--mode=block",
        "--who=" + WHO,
        "--why=Audio processing must not be written into a hibernation image",
    ]
    if args.elevate_inhibitor:
        import pwd

        inhibit_command = [
            "sudo" if sys.stdin.isatty() else "pkexec",
            *inhibit_command,
            "runuser",
            "-u",
            pwd.getpwuid(os.getuid()).pw_name,
            "--",
        ]
    inhibit_command += [sys.executable, str(helper), *cmd]
    inhibitor = subprocess.Popen(inhibit_command, stdin=subprocess.PIPE, cwd=ROOT)
    try:
        deadline = time.monotonic() + (120 if args.elevate_inhibitor else 10)
        while time.monotonic() < deadline:
            if inhibitor.poll() is not None:
                raise RuntimeError("Could not acquire the host sleep/shutdown inhibitor.")
            if any(
                row["who"] == WHO
                and row["mode"] == "block"
                and "sleep" in row["what"]
                and "shutdown" in row["what"]
                for row in inhibitors()
            ):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("The host did not confirm the sleep inhibitor.")

        def heartbeat():
            while not stop.is_set():
                try:
                    protected = inhibitor.poll() is None and any(
                        row["who"] == WHO and row["mode"] == "block" for row in inhibitors()
                    )
                    write_guard(protected)
                    if not protected:
                        guard_failure.set()
                        stop.set()
                        return
                except Exception:
                    guard_failure.set()
                    stop.set()
                    return
                stop.wait(1)

        write_guard(True)
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        subprocess.run([*cmd, "up", "-d", "--no-build"], check=True, cwd=ROOT)
        if args.tls_domain:
            from provision_tls import provision

            provision(cmd, args.tls_domain)
        elif args.local_tls:
            from provision_tls import provision_pem

            provision_pem(cmd, pem)
        elif args.isolated_share:
            from provision_tls import provision_pem
            from share_node import certificate, check_app, enable

            provision_pem(cmd, certificate(cmd, name))
            check_app(cmd, name)
            enable(cmd)
        address = (
            f"https://{args.tls_domain}:8445"
            if args.tls_domain
            else f"https://{name}:8445"
            if args.isolated_share
            else "https://localhost:8787"
            if args.local_tls
            else "http://127.0.0.1:8787"
        )
        print(f"Hushscript: {address} — Ctrl+C stops and clears server memory.", flush=True)
        while not stop.wait(5 if args.isolated_share else 1):
            if inhibitor.poll() is not None:
                raise RuntimeError("Host sleep inhibitor stopped.")
            if args.isolated_share and domain(cmd) != name:
                raise RuntimeError("The isolated Tailscale node stopped or changed identity.")
        if guard_failure.is_set():
            raise RuntimeError("Host privacy verification failed; stopping Hushscript.")
    finally:
        stop.set()
        if "thread" in locals():
            thread.join(timeout=6)
        write_guard(False)
        # The helper stops Docker before releasing its independent inhibitor.
        if inhibitor.stdin:
            inhibitor.stdin.close()
        try:
            inhibitor.wait(timeout=40)
        except subprocess.TimeoutExpired:
            # Do not terminate the inhibitor while a container may still hold inputs.
            print(
                "Container stop is taking longer than expected; sleep stays inhibited.",
                file=sys.stderr,
            )
            inhibitor.wait()


if __name__ == "__main__":
    main()
