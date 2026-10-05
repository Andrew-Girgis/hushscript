"""Manage the isolated Tailscale identity without touching the host node."""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "-f",
    str(ROOT / "compose.yaml"),
    "-f",
    str(ROOT / "compose.isolated.yaml"),
]


def domain(command=COMPOSE):
    try:
        raw = subprocess.check_output(
            [*command, "exec", "-T", "tailnet", "tailscale", "status", "--json"],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        status = json.loads(raw)
        name = status["Self"]["DNSName"].rstrip(".")
        if status["BackendState"] != "Running" or not name.endswith(".ts.net"):
            raise ValueError("The isolated node is not connected to Tailscale.")
        return name
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        raise RuntimeError(
            "The isolated Hushscript node is not connected. "
            "Run python3 scripts/share_node.py setup."
        ) from error


def app_running():
    output = subprocess.check_output(
        [*COMPOSE, "ps", "--status", "running", "--services"],
        timeout=10,
    )
    return "app" in output.decode().splitlines()


def certificate(command, name):
    return subprocess.check_output(
        [
            *command,
            "exec",
            "-T",
            "tailnet",
            "tailscale",
            "cert",
            "--cert-file",
            "-",
            "--key-file",
            "-",
            "--min-validity",
            "48h",
            name,
        ],
        timeout=90,
    )


def check_app(command, name):
    # The new process only makes a loopback health request; it sees no audio.
    code = """
import http.client,json,socket,ssl
raw=socket.create_connection(('127.0.0.1',8787),timeout=5)
conn=http.client.HTTPConnection('127.0.0.1',8787,timeout=5)
try:
    conn.sock=ssl.create_default_context().wrap_socket(raw,server_hostname=__import__('sys').argv[1])
    conn.request('GET','/api/health',headers={'Host':__import__('sys').argv[1]})
    response=conn.getresponse()
    if response.status!=200 or not json.load(response).get('ready'):
        raise SystemExit('Protected app is not ready')
finally:
    conn.close()
"""
    subprocess.run(
        [*command, "exec", "-T", "app", "python", "-c", code, name],
        check=True,
        timeout=15,
    )


def enable(command):
    subprocess.run(
        [
            *command,
            "exec",
            "-T",
            "tailnet",
            "tailscale",
            "serve",
            "--bg",
            "--tcp=8445",
            "tcp://127.0.0.1:8787",
        ],
        check=True,
        timeout=20,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "status"))
    args = parser.parse_args()
    if args.action == "setup":
        subprocess.run([*COMPOSE, "up", "-d", "--no-build", "tailnet"], check=True, cwd=ROOT)
        try:
            name = domain()
        except RuntimeError:
            print("Sign in to the isolated Hushscript node with your own Tailscale account.")
            subprocess.run([*COMPOSE, "exec", "tailnet", "tailscale", "login"], check=True)
            name = domain()
    else:
        name = domain()
    print(f"Isolated node: {name}")
    print("This node has no host ports and does not share Omphalos's other services.")


if __name__ == "__main__":
    main()
